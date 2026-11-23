from hashlib import sha256

from sqlalchemy import func, select, text, update

from cross_market.modules.alerts.infrastructure.repository import lock_writes, utc
from cross_market.modules.alerts.infrastructure.schedule_models import (
    AlertSchedule,
    AlertScheduleRun,
)
from cross_market.shared.exceptions import AppError


async def ensure_capacity(session):
    """创建容量锁仅由HTTP调用，连接终结回调在提交或回滚后释放。"""
    connection = await session.connection()
    if connection.dialect.name == "mysql":
        database = await session.scalar(text("SELECT DATABASE()"))
        key = "tickradar:" + sha256(str(database).encode()).hexdigest()[:32] + ":schedules"
        if await session.scalar(text("SELECT GET_LOCK(:key, 5)"), {"key": key}) != 1:
            raise AppError(503, "SCHEDULE_WRITE_BUSY", "提醒创建繁忙，请稍后重试")

        async def release(connection):
            if await connection.scalar(text("SELECT RELEASE_LOCK(:key)"), {"key": key}) != 1:
                raise AppError(503, "SCHEDULE_LOCK_RELEASE_FAILED", "提醒写入连接需重建")
            await connection.rollback()

        session.info.setdefault("connection_finalizers", []).append(release)
    count = await session.scalar(
        select(func.count()).select_from(AlertSchedule).where(AlertSchedule.is_deleted.is_(False))
    )
    if count >= 50:
        raise AppError(409, "SCHEDULE_CAPACITY_EXCEEDED", "最多保存50个未归档尾盘提醒")


async def get(session, schedule_id, *, lock=False):
    query = select(AlertSchedule).where(
        AlertSchedule.id == schedule_id, AlertSchedule.is_deleted.is_(False)
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = await session.scalar(query)
    if row is None:
        raise AppError(404, "SCHEDULE_NOT_FOUND", "尾盘提醒不存在")
    return row


async def list_schedules(session, *, active=False):
    query = select(AlertSchedule).where(AlertSchedule.is_deleted.is_(False))
    if active:
        query = query.where(AlertSchedule.enabled.is_(True))
    return list(await session.scalars(query.order_by(AlertSchedule.created_at, AlertSchedule.id)))


async def change(session, row, version, values):
    result = await session.execute(
        update(AlertSchedule)
        .where(
            AlertSchedule.id == row.id,
            AlertSchedule.version == version,
            AlertSchedule.is_deleted.is_(False),
        )
        .values(**values, version=version + 1)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise AppError(409, "SCHEDULE_VERSION_CONFLICT", "尾盘提醒已变更，请重新加载")
    await session.refresh(row)


async def today_runs(session, schedule_id, day, *, lock=False):
    query = select(AlertScheduleRun).where(
        AlertScheduleRun.schedule_id == schedule_id, AlertScheduleRun.session_date == day
    )
    if lock:
        # MySQL当前读，不能沿用等待配置行锁之前建立的旧快照。
        query = query.with_for_update().execution_options(populate_existing=True)
    return {row.local_time: row for row in await session.scalars(query)}


async def list_runs(session, schedule_id, page, page_size):
    query = select(AlertScheduleRun)
    if schedule_id is not None:
        query = query.where(AlertScheduleRun.schedule_id == schedule_id)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    items = list(
        await session.scalars(
            query.order_by(AlertScheduleRun.created_at.desc(), AlertScheduleRun.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return dict(items=items, total=total, page=page, page_size=page_size)


__all__ = [
    "change",
    "ensure_capacity",
    "get",
    "list_runs",
    "list_schedules",
    "lock_writes",
    "today_runs",
    "utc",
]
