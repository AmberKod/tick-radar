from dataclasses import asdict, fields
from datetime import UTC
from hashlib import sha256

from sqlalchemy import func, select, text, update

from cross_market.modules.alerts.domain.engine import State
from cross_market.modules.alerts.infrastructure.models import AlertEvent, AlertRule, AlertRuleState
from cross_market.shared.exceptions import AppError


def utc(value):
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def state_value(row):
    values = {field.name: getattr(row, field.name) for field in fields(State)}
    for key in ("last_received_at", "last_triggered_at", "last_reset_at", "checked_at"):
        values[key] = utc(values[key])
    return State(**values)


def save_state(row, state):
    for key, value in asdict(state).items():
        setattr(row, key, value)


async def lock_writes(session):
    connection = await session.connection()
    if connection.dialect.name == "sqlite":
        # 每个事务重新判断，session 可被 Worker 跨事务复用。
        raw = await connection.get_raw_connection()
        if not raw.driver_connection.in_transaction:
            await session.execute(text("BEGIN IMMEDIATE"))


async def ensure_capacity(session):
    """序列化创建时的容量检查，避免超出Worker可扫描范围而静默失效。"""
    connection = await session.connection()
    if connection.dialect.name == "mysql":
        database = await session.scalar(text("SELECT DATABASE()"))
        key = "tickradar:" + sha256(str(database).encode()).hexdigest()[:32] + ":alerts"
        if await session.scalar(text("SELECT GET_LOCK(:key, 5)"), {"key": key}) != 1:
            raise AppError(503, "ALERT_WRITE_BUSY", "规则创建繁忙，请稍后重试")

        async def release(connection):
            if await connection.scalar(text("SELECT RELEASE_LOCK(:key)"), {"key": key}) != 1:
                raise AppError(503, "ALERT_LOCK_RELEASE_FAILED", "规则写入连接需重建")
            await connection.rollback()

        session.info.setdefault("connection_finalizers", []).append(release)
    count = await session.scalar(select(func.count()).select_from(AlertRule).where(
        AlertRule.is_deleted.is_(False)
    ))
    if count >= 200:
        raise AppError(
            409, "ALERT_CAPACITY_EXCEEDED", "最多保存200条未归档规则，请先删除不用的规则"
        )


async def rule(session, rule_id, *, lock=False):
    statement = select(AlertRule).where(AlertRule.id == rule_id, AlertRule.is_deleted.is_(False))
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    row = await session.scalar(statement)
    if row is None:
        raise AppError(404, "ALERT_NOT_FOUND", "提醒规则不存在")
    return row


async def state(session, rule_id, *, lock=False):
    statement = select(AlertRuleState).where(AlertRuleState.rule_id == rule_id)
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    return await session.scalar(statement)


async def rules(session, *, active=False, limit=None):
    statement = select(AlertRule).where(AlertRule.is_deleted.is_(False))
    if active:
        statement = statement.where(AlertRule.enabled.is_(True), AlertRule.mode == "OBSERVATION")
    statement = statement.order_by(AlertRule.created_at, AlertRule.id)
    if limit is not None:
        statement = statement.limit(limit)
    return list(await session.scalars(statement))


async def versioned_change(session, row, version, values):
    result = await session.execute(
        update(AlertRule)
        .where(
            AlertRule.id == row.id, AlertRule.version == version, AlertRule.is_deleted.is_(False)
        )
        .values(**values, version=version + 1)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise AppError(409, "ALERT_VERSION_CONFLICT", "提醒规则已变更，请重新加载")
    await session.refresh(row)


async def events(session, rule_id, page, page_size):
    statement = select(AlertEvent)
    if rule_id is not None:
        statement = statement.where(AlertEvent.rule_id == rule_id)
    total = await session.scalar(select(func.count()).select_from(statement.subquery()))
    rows = await session.scalars(
        statement.order_by(AlertEvent.created_at.desc(), AlertEvent.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(rows), total


async def event_exists(session, rule_id, trigger_number):
    return await session.scalar(
        select(AlertEvent.id).where(
            AlertEvent.rule_id == rule_id,
            AlertEvent.trigger_number == trigger_number,
        )
    )
