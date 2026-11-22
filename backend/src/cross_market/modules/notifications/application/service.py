import json
from collections.abc import Awaitable, Callable
from datetime import UTC, timedelta
from uuid import UUID

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError

from cross_market.modules.notifications.infrastructure.models import (
    InboxMessage,
    NotificationDelivery,
    NotificationOutbox,
    utcnow,
)
from cross_market.shared.exceptions import AppError

Adapter = Callable[..., Awaitable[None]]


async def _write_lock(session):
    connection = await session.connection()
    if connection.dialect.name == "sqlite":
        raw = await connection.get_raw_connection()
        if not raw.driver_connection.in_transaction:
            await session.execute(text("BEGIN IMMEDIATE"))


def _time(value):
    value = value or utcnow()
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("时间必须包含时区")
    return value.astimezone(UTC)


def _snapshot(event_id, title, body, payload):
    try:
        event_id = str(UUID(str(event_id)))
        if not isinstance(title, str) or not 1 <= len(title) <= 160:
            raise ValueError
        if not isinstance(body, str) or not 1 <= len(body) <= 2000:
            raise ValueError
        if not isinstance(payload, dict):
            raise ValueError
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        if len(encoded.encode("utf-8")) > 65536:
            raise ValueError
        payload = json.loads(encoded)
    except (ValueError, TypeError, RecursionError, OverflowError) as exc:
        raise AppError(422, "NOTIFICATION_INVALID", "通知内容无效或超过长度限制") from exc
    return event_id, title, body, payload


async def enqueue(session, event_id, title, body, payload) -> str:
    event_id, title, body, payload = _snapshot(event_id, title, body, payload)
    await _write_lock(session)
    statement = select(NotificationOutbox).where(NotificationOutbox.event_id == event_id)
    existing = await session.scalar(statement)
    if existing is None:
        row = NotificationOutbox(event_id=event_id, title=title, body=body, payload=payload)
        try:
            async with session.begin_nested():
                session.add(row)
                await session.flush()
            return row.id
        except IntegrityError:
            existing = await session.scalar(statement.with_for_update())
            if existing is None:
                raise
    if (existing.title, existing.body, existing.payload) != (title, body, payload):
        raise AppError(409, "NOTIFICATION_EVENT_CONFLICT", "该事件已存在不同的通知内容")
    return existing.id


async def deliver_in_app(session, outbox, now):
    existing = await session.scalar(select(InboxMessage).where(InboxMessage.outbox_id == outbox.id))
    if existing is None:
        session.add(
            InboxMessage(
                outbox_id=outbox.id,
                event_id=outbox.event_id,
                title=outbox.title,
                body=outbox.body,
                payload=outbox.payload,
                created_at=now,
            )
        )
        await session.flush()


async def dispatch_pending(session, now=None, limit=50, *, adapter: Adapter | None = None) -> dict:
    """站内写入在调用者事务中执行；Worker提交前再次核对所有权。"""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
        raise ValueError("limit 必须为 1 到 500 的整数")
    now = _time(now)
    await _write_lock(session)
    rows = (
        await session.scalars(
            select(NotificationOutbox)
            .where(
                NotificationOutbox.status.in_(("PENDING", "RETRY")),
                NotificationOutbox.next_attempt_at <= now,
            )
            .order_by(NotificationOutbox.next_attempt_at, NotificationOutbox.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
    ).all()
    result = {"sent": 0, "failed": 0, "pending": 0}
    for row in rows:
        error = None
        try:
            async with session.begin_nested():
                await (adapter or deliver_in_app)(session, row, now)
                await session.flush()
        except Exception as exc:
            # 不保留异常正文，避免把驱动参数或敏感内容写入公开接口。
            error = type(exc).__name__[:160]
        row.attempts += 1
        if error is None:
            row.status, row.sent_at, row.last_error = "SENT", now, None
            result["sent"] += 1
        else:
            row.last_error = error
            row.status = "DEAD" if row.attempts >= row.max_attempts else "RETRY"
            row.next_attempt_at = now + timedelta(seconds=min(300, 2 ** min(row.attempts, 9)))
            result["failed"] += 1
        session.add(
            NotificationDelivery(
                outbox_id=row.id,
                attempt=row.attempts,
                status="SENT" if error is None else "FAILED",
                error_code=error,
                created_at=now,
            )
        )
        await session.flush()
    result["pending"] = await session.scalar(
        select(func.count())
        .select_from(NotificationOutbox)
        .where(NotificationOutbox.status.in_(("PENDING", "RETRY")))
    )
    return result


async def get_outbox(session, outbox_id, *, lock=False):
    query = select(NotificationOutbox).where(NotificationOutbox.id == outbox_id)
    if lock:
        await _write_lock(session)
        query = query.with_for_update().execution_options(populate_existing=True)
    row = await session.scalar(query)
    if row is None:
        raise AppError(404, "NOTIFICATION_NOT_FOUND", "通知不存在")
    return row


async def retry_outbox(session, outbox_id):
    row = await get_outbox(session, outbox_id, lock=True)
    if row.status == "PENDING":
        return row
    if row.status not in ("DEAD", "RETRY"):
        raise AppError(409, "NOTIFICATION_RETRY_NOT_ALLOWED", "当前通知不允许重试")
    row.status, row.next_attempt_at = "PENDING", utcnow()
    row.max_attempts = row.attempts + 5
    await session.flush()
    return row


async def list_inbox(session, page, page_size, unread_only=False):
    filters = [InboxMessage.read_at.is_(None)] if unread_only else []
    total = await session.scalar(select(func.count()).select_from(InboxMessage).where(*filters))
    unread = await session.scalar(
        select(func.count()).select_from(InboxMessage).where(InboxMessage.read_at.is_(None))
    )
    items = (
        await session.scalars(
            select(InboxMessage)
            .where(*filters)
            .order_by(InboxMessage.created_at.desc(), InboxMessage.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return dict(items=items, total=total, page=page, page_size=page_size, unread_count=unread)


async def mark_read(session, message_id):
    await _write_lock(session)
    row = await session.scalar(
        select(InboxMessage)
        .where(InboxMessage.id == message_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise AppError(404, "NOTIFICATION_NOT_FOUND", "通知不存在")
    if row.read_at is None:
        row.read_at = utcnow()
        await session.flush()
    return row


async def read_all(session):
    await _write_lock(session)
    result = await session.execute(
        update(InboxMessage).where(InboxMessage.read_at.is_(None)).values(read_at=utcnow())
    )
    return {"updated": result.rowcount}


async def list_outbox(session, page, page_size, status=None):
    filters = [NotificationOutbox.status == status] if status else []
    total = await session.scalar(
        select(func.count()).select_from(NotificationOutbox).where(*filters)
    )
    items = (
        await session.scalars(
            select(NotificationOutbox)
            .where(*filters)
            .order_by(NotificationOutbox.created_at.desc(), NotificationOutbox.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return dict(items=items, total=total, page=page, page_size=page_size)


async def list_deliveries(session, outbox_id):
    await get_outbox(session, outbox_id)
    items = (
        await session.scalars(
            select(NotificationDelivery)
            .where(NotificationDelivery.outbox_id == outbox_id)
            .order_by(NotificationDelivery.attempt)
        )
    ).all()
    return {"items": items}
