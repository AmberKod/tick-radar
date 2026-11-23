from datetime import UTC, datetime, time, timedelta
from uuid import uuid4

from cross_market.modules.alerts.application.schedule_schemas import (
    ScheduleList,
    SchedulePreview,
    ScheduleResponse,
    ScheduleSlotPreview,
)
from cross_market.modules.alerts.domain.schedules import ZONE, Calendar, aware_utc, decide_slot
from cross_market.modules.alerts.infrastructure import schedule_repository as repo
from cross_market.modules.alerts.infrastructure.schedule_models import (
    AlertSchedule,
    AlertScheduleRun,
)
from cross_market.modules.market_calendar.application.schemas import MarketCalendarStatus
from cross_market.modules.notifications.application.service import enqueue


async def list_schedules(session):
    return ScheduleList(
        items=[ScheduleResponse.model_validate(row) for row in await repo.list_schedules(session)]
    )


async def get_schedule(session, schedule_id):
    return ScheduleResponse.model_validate(await repo.get(session, schedule_id))


async def create_schedule(session, body):
    await repo.lock_writes(session)
    await repo.ensure_capacity(session)
    row = AlertSchedule(**body.model_dump())
    session.add(row)
    await session.flush()
    return ScheduleResponse.model_validate(row)


async def update_schedule(session, schedule_id, body):
    await repo.lock_writes(session)
    row = await repo.get(session, schedule_id, lock=True)
    await repo.change(
        session,
        row,
        body.version,
        {
            **body.model_dump(exclude={"version"}),
            "updated_at": datetime.now(UTC),
        },
    )
    return ScheduleResponse.model_validate(row)


async def delete_schedule(session, schedule_id, version):
    await repo.lock_writes(session)
    row = await repo.get(session, schedule_id, lock=True)
    await repo.change(
        session,
        row,
        version,
        {
            "enabled": False,
            "is_deleted": True,
            "updated_at": datetime.now(UTC),
        },
    )


async def list_runs(session, *, schedule_id=None, page=1, page_size=20):
    return await repo.list_runs(session, schedule_id, page, page_size)


def calendar_snapshot(calendar, exchange, now):
    """异常降级为可追溯UNKNOWN，不从工作日推断交易日。"""
    try:
        return calendar.get_status(exchange, now)
    except Exception:
        day = now.astimezone(ZONE).date()
        return MarketCalendarStatus(
            exchange=exchange,
            market="CN",
            state="UNKNOWN",
            timezone="Asia/Shanghai",
            local_time=now.astimezone(ZONE),
            checked_at=now,
            session_date=day,
            calendar_name="UNAVAILABLE",
            calendar_version="UNAVAILABLE",
            coverage_start=day,
            coverage_end=day,
            basis="UNAVAILABLE",
            reason="日历服务不可用，暂停提醒",
        )


def primitive(status, exchange):
    return Calendar(
        session_date=status.session_date,
        is_trading_day=status.is_trading_day,
        state=status.state,
        basis=status.basis,
        coverage_start=status.coverage_start,
        coverage_end=status.coverage_end,
        session_open=status.session_open,
        session_close=status.session_close,
        break_start=status.break_start,
        break_end=status.break_end,
        identity_valid=(
            status.exchange == exchange
            and status.market == "CN"
            and status.timezone == "Asia/Shanghai"
        ),
    )


async def plan(session, row, calendar, now, *, lock=False):
    now = aware_utc(now)
    day = now.astimezone(ZONE).date()
    status = calendar_snapshot(calendar, row.exchange, now)
    previous = await repo.today_runs(session, row.id, day, lock=lock)
    slots = []
    for label in row.times:
        due = datetime.combine(day, time.fromisoformat(label), ZONE).astimezone(UTC)
        existing = previous.get(label)
        decision = decide_slot(
            now=now,
            scheduled_at=due,
            active_since=repo.utc(row.updated_at),
            grace_seconds=row.grace_seconds,
            calendar=primitive(status, row.exchange),
            enabled=row.enabled,
            existing_status=existing.status if existing else None,
        )
        expiry = decision.expires_at
        if existing:
            # 历史记录的窗口按生成时快照冻结，不随配置或日历修订漂移。
            due = repo.utc(existing.scheduled_at)
            expiry = due + timedelta(seconds=existing.rule_snapshot["grace_seconds"])
            close = existing.calendar.get("session_close")
            if close:
                expiry = min(expiry, aware_utc(datetime.fromisoformat(close)))
        slots.append(
            ScheduleSlotPreview(
                local_time=label,
                scheduled_at=due,
                expires_at=expiry,
                status=decision.status,
                reason=existing.reason if existing else decision.reason,
                run_id=existing.id if existing else None,
                outbox_id=existing.outbox_id if existing else None,
            )
        )
    return SchedulePreview(schedule_id=row.id, checked_at=now, calendar=status, slots=slots)


async def preview_schedule(session, schedule_id, calendar, now=None):
    row = await repo.get(session, schedule_id)
    return await plan(session, row, calendar, aware_utc(now or datetime.now(UTC)))


async def evaluate_schedules(session, calendar, now):
    now = aware_utc(now)
    await repo.lock_writes(session)
    targets = await repo.list_schedules(session, active=True)
    result = dict(evaluated=0, enqueued=0, missed=0, skipped=0)
    for target in targets:
        # 更新/停用与评估串行，行锁后必须重新读取最新配置。
        try:
            row = await repo.get(session, target.id, lock=True)
        except Exception as exc:
            from cross_market.shared.exceptions import AppError

            if isinstance(exc, AppError) and exc.status == 404:
                continue
            raise
        if not row.enabled:
            continue
        preview = await plan(session, row, calendar, now, lock=True)
        for slot in preview.slots:
            if slot.status == "SKIPPED":
                result["skipped"] += 1
                continue
            if slot.run_id or slot.status not in {"ENQUEUE", "MISSED"}:
                continue
            record = AlertScheduleRun(
                id=str(uuid4()),
                schedule_id=row.id,
                schedule_name=row.name,
                schedule_version=row.version,
                exchange=row.exchange,
                session_date=now.astimezone(ZONE).date(),
                local_time=slot.local_time,
                scheduled_at=slot.scheduled_at,
                status="ENQUEUED" if slot.status == "ENQUEUE" else "MISSED",
                reason=slot.reason,
                rule_snapshot=ScheduleResponse.model_validate(row).model_dump(mode="json"),
                calendar=preview.calendar.model_dump(mode="json"),
                created_at=now,
            )
            session.add(record)
            await session.flush()
            if slot.status == "ENQUEUE":
                record.outbox_id = await enqueue(
                    session,
                    record.id,
                    "尾盘提醒：" + row.name,
                    row.message + "\n交易日定时提醒，不代表行情条件已满足。",
                    {
                        "kind": "SCHEDULE_REMINDER",
                        "schedule_id": row.id,
                        "schedule_version": row.version,
                        "run_id": record.id,
                        "session_date": record.session_date.isoformat(),
                        "local_time": slot.local_time,
                        "exchange": row.exchange,
                        "timezone": "Asia/Shanghai",
                        "scheduled_at": slot.scheduled_at.isoformat(),
                        "expires_at": slot.expires_at.isoformat(),
                        "calendar_basis": preview.calendar.basis,
                    },
                )
                result["enqueued"] += 1
            else:
                result["missed"] += 1
            result["evaluated"] += 1
            await session.flush()
    return result
