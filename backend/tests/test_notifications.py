import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cross_market.modules.notifications.application import service
from cross_market.modules.notifications.infrastructure.models import (
    InboxMessage,
    NotificationDelivery,
    NotificationOutbox,
)
from cross_market.modules.notifications.interfaces.router import router
from cross_market.shared.exceptions import AppError, register_exception_handlers

TABLES = [NotificationOutbox.__table__, NotificationDelivery.__table__, InboxMessage.__table__]
TOKEN = {"Authorization": "Bearer test-token"}
PREFIX = "/api/v1/notifications"


@pytest.fixture
async def factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'notifications.db'}")
    async with engine.begin() as connection:
        for table in TABLES:
            await connection.run_sync(table.create)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def add(factory, event_id=None):
    async with factory() as session, session.begin():
        return await service.enqueue(session, event_id or uuid4(), "测试", "正文", {"x": 1})


async def test_enqueue_idempotency_and_rollback(factory):
    event_id = uuid4()
    async with factory() as session:
        first = await service.enqueue(session, event_id, "测试", "正文", {"x": 1})
        assert await service.enqueue(session, event_id, "测试", "正文", {"x": 1}) == first
        with pytest.raises(AppError) as error:
            await service.enqueue(session, event_id, "改变", "正文", {})
        assert error.value.status == 409
        await session.rollback()
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(NotificationOutbox)) == 0


@pytest.mark.parametrize(
    "values",
    [
        ("x", "正文", []),
        ("x" * 161, "正文", {}),
        ("x", "x" * 2001, {}),
        ("x", "正文", {"x": "x" * 65536}),
        ("x", "正文", {"x": float("nan")}),
    ],
)
async def test_snapshot_validation(factory, values):
    async with factory() as session:
        with pytest.raises(AppError) as error:
            await service.enqueue(session, uuid4(), *values)
        assert error.value.status == 422


async def test_dispatch_concurrency_and_transaction(factory):
    outbox_id = await add(factory)

    async def dispatch():
        async with factory() as session, session.begin():
            return await service.dispatch_pending(session)

    results = await asyncio.gather(dispatch(), dispatch())
    assert sum(value["sent"] for value in results) == 1
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(InboxMessage)) == 1
        assert await session.scalar(select(func.count()).select_from(NotificationDelivery)) == 1
        row = await service.get_outbox(session, outbox_id)
        assert row.status == "SENT" and row.sent_at.tzinfo is UTC
        with pytest.raises(AppError) as error:
            await service.retry_outbox(session, outbox_id)
        assert error.value.code == "NOTIFICATION_RETRY_NOT_ALLOWED"


async def test_failed_adapter_savepoint_dead_and_manual_retry(factory):
    outbox_id = await add(factory)
    now = datetime.now(UTC) + timedelta(seconds=1)

    async def fail(session, row, at):
        await service.deliver_in_app(session, row, at)
        raise RuntimeError("不能公开的内容")

    for attempt in range(1, 6):
        async with factory() as session, session.begin():
            result = await service.dispatch_pending(session, now, adapter=fail)
            assert result["failed"] == 1
            row = await service.get_outbox(session, outbox_id)
            assert row.attempts == attempt
            assert row.next_attempt_at == now + timedelta(seconds=2**attempt)
            assert row.last_error == "RuntimeError"
            assert await session.scalar(select(func.count()).select_from(InboxMessage)) == 0
            now = row.next_attempt_at
    async with factory() as session, session.begin():
        row = await service.retry_outbox(session, outbox_id)
        assert row.status == "PENDING" and row.attempts == 5 and row.max_attempts == 10
        due = row.next_attempt_at
        row = await service.retry_outbox(session, outbox_id)
        assert row.next_attempt_at == due and row.max_attempts == 10
    async with factory() as session, session.begin():
        assert (await service.dispatch_pending(session, now))["sent"] == 1
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(InboxMessage)) == 1
        assert await session.scalar(select(func.count()).select_from(NotificationDelivery)) == 6


async def test_database_failure_does_not_poison_session(factory):
    outbox_id = await add(factory)

    async def invalid_write(session, row, now):
        session.add(
            InboxMessage(
                outbox_id=row.id,
                event_id=row.event_id,
                title=None,
                body=row.body,
                payload=row.payload,
                created_at=now,
            )
        )
        await session.flush()

    async with factory() as session, session.begin():
        result = await service.dispatch_pending(session, adapter=invalid_write)
        assert result["failed"] == 1
        row = await service.get_outbox(session, outbox_id)
        assert row.status == "RETRY" and row.last_error == "IntegrityError"
        assert await session.scalar(select(func.count()).select_from(InboxMessage)) == 0
        assert await session.scalar(select(func.count()).select_from(NotificationDelivery)) == 1


async def test_read_all_updates_only_unread(factory):
    await add(factory)
    await add(factory)
    async with factory() as session, session.begin():
        await service.dispatch_pending(session)
    async with factory() as session, session.begin():
        assert await service.read_all(session) == {"updated": 2}
    async with factory() as session, session.begin():
        assert await service.read_all(session) == {"updated": 0}
        page = await service.list_inbox(session, 1, 1)
        assert page["total"] == 2 and len(page["items"]) == 1 and page["unread_count"] == 0


async def test_dispatch_rollback_and_cancellation(factory):
    outbox_id = await add(factory)
    async with factory() as session:
        assert (await service.dispatch_pending(session))["sent"] == 1
        await session.rollback()

    async def cancel(session, row, now):
        await service.deliver_in_app(session, row, now)
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        async with factory() as session, session.begin():
            await service.dispatch_pending(session, adapter=cancel)
    async with factory() as session:
        assert (await service.get_outbox(session, outbox_id)).attempts == 0
        assert await session.scalar(select(func.count()).select_from(InboxMessage)) == 0
        assert await session.scalar(select(func.count()).select_from(NotificationDelivery)) == 0


@pytest.fixture
async def client(factory):
    app = FastAPI()
    app.state.settings = SimpleNamespace(api_token=SecretStr("test-token"))
    app.state.session_factory = factory
    app.state.engine = factory.kw["bind"]
    register_exception_handlers(app)
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as value:
        value.test_app = app
        yield value


async def test_http_inbox_and_read_idempotence(client, factory):
    request = {"request_id": str(uuid4())}
    first = await client.post(PREFIX + "/test", json=request, headers=TOKEN)
    assert first.status_code == 201, first.text
    row = first.json()
    assert row["title"] == "站内通知测试" and row["channel"] == "IN_APP"
    again = await client.post(PREFIX + "/test", json=request, headers=TOKEN)
    assert again.json()["id"] == row["id"]
    async with factory() as session, session.begin():
        await service.dispatch_pending(session)
    page = (await client.get(PREFIX + "/inbox", headers=TOKEN)).json()
    assert page["total"] == page["unread_count"] == 1
    message = page["items"][0]
    assert message["created_at"].endswith("Z")
    url = PREFIX + f"/inbox/{message['id']}/read"
    read = await client.put(url, headers=TOKEN)
    assert read.status_code == 200, read.text
    assert read.json()["read_at"].endswith("Z")
    assert (await client.put(url, json={"read": True}, headers=TOKEN)).json() == read.json()
    unread = await client.get(PREFIX + "/inbox?unread_only=true", headers=TOKEN)
    assert unread.json()["total"] == 0
    assert (await client.post(PREFIX + "/inbox/read-all", headers=TOKEN)).json() == {"updated": 0}
    deliveries = await client.get(PREFIX + f"/outbox/{row['id']}/deliveries", headers=TOKEN)
    assert deliveries.json()["items"][0]["attempt"] == 1
    assert (await client.get(PREFIX + "/outbox?status=SENT", headers=TOKEN)).json()["total"] == 1
    retry = await client.post(PREFIX + f"/outbox/{row['id']}/retry", headers=TOKEN)
    assert retry.status_code == 409


async def test_http_auth_validation_and_missing(client):
    assert (await client.get(PREFIX + "/inbox")).status_code == 401
    for path in ("/inbox?page=0", "/inbox?page_size=101", "/outbox?status=SENDING"):
        assert (await client.get(PREFIX + path, headers=TOKEN)).status_code == 422
    for body in ({}, {"request_id": "bad"}, {"request_id": str(uuid4()), "extra": True}):
        assert (await client.post(PREFIX + "/test", json=body, headers=TOKEN)).status_code == 422
    missing = str(uuid4())
    for path in (f"/outbox/{missing}/deliveries",):
        assert (await client.get(PREFIX + path, headers=TOKEN)).status_code == 404
    assert (await client.put(PREFIX + f"/inbox/{missing}/read", headers=TOKEN)).status_code == 404
    for body in ({"read": False}, {"extra": True}, {"read": "true"}, {"read": 1}):
        assert (
            await client.put(PREFIX + f"/inbox/{missing}/read", json=body, headers=TOKEN)
        ).status_code == 422
    client.test_app.state.settings.api_token = SecretStr("")
    assert (await client.get(PREFIX + "/inbox", headers=TOKEN)).status_code == 503
