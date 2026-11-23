import asyncio
import json
import sys
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fakeredis.aioredis import FakeRedis

from cross_market.apps.worker.alert_tasks import OwnerLost
from cross_market.apps.worker.runtime import WorkerRuntime
from cross_market.apps.worker.schedule_tasks import schedule_once, schedule_reminder
from cross_market.apps.worker.task_registry import registered_tasks
from cross_market.modules.system.infrastructure.task_status import task_statuses
from cross_market.shared.config import Settings


@pytest.mark.parametrize(
    ("counts", "expected"),
    [
        (dict(evaluated=1, enqueued=1, missed=0, skipped=0),
         ("success", 1, 0, "SCHEDULES_EVALUATED")),
        (dict(evaluated=1, enqueued=0, missed=1, skipped=0),
         ("success", 1, 0, "SCHEDULES_EVALUATED")),
        (dict(evaluated=0, enqueued=0, missed=0, skipped=1),
         ("partial", 0, 1, "CALENDAR_UNAVAILABLE")),
        (dict(evaluated=0, enqueued=0, missed=0, skipped=0),
         ("idle", 0, 0, "NO_ENABLED_SCHEDULES")),
    ],
)
async def test_schedule_result_and_utc_clock(monkeypatch, counts, expected):
    from test_alert_worker import TransactionSession

    session = TransactionSession()
    calendar = object()
    evaluate = AsyncMock(return_value=counts)
    monkeypatch.setitem(
        sys.modules, "cross_market.modules.alerts.application.schedules",
        SimpleNamespace(evaluate_schedules=evaluate),
    )
    async with FakeRedis(decode_responses=True) as redis:
        worker = WorkerRuntime(redis, Settings())
        await redis.set(worker.settings.worker_lock_key, worker.owner)
        before = datetime.now(UTC)
        assert await schedule_once(
            worker, session_factory=session.factory, calendar=calendar
        ) == expected
        args = evaluate.await_args.args
        assert args[:2] == (session, calendar)
        assert args[2].tzinfo is UTC and before <= args[2] <= datetime.now(UTC)
        assert session.committed and session.closed and not session.rolled_back


@pytest.mark.parametrize("loss", ["before", "commit", "stop", "cancel"])
async def test_schedule_real_transaction_rolls_back_all_writes(monkeypatch, tmp_path, loss):
    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from cross_market.modules.notifications.application.service import enqueue
    from cross_market.modules.notifications.infrastructure.models import NotificationOutbox

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'rollback.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    entered = asyncio.Event()
    try:
        async with engine.begin() as connection:
            await connection.run_sync(NotificationOutbox.__table__.create)
        async with FakeRedis(decode_responses=True) as redis:
            worker = WorkerRuntime(redis, Settings())
            await redis.set(
                worker.settings.worker_lock_key, "replacement" if loss == "before" else worker.owner
            )

            async def evaluate(session, calendar, now):
                await enqueue(
                    session, "00000000-0000-4000-8000-000000000001", "测试提醒", "测试内容", {}
                )
                await session.flush()
                entered.set()
                if loss == "cancel":
                    await asyncio.Event().wait()
                elif loss == "stop":
                    worker.stop_event.set()
                else:
                    await redis.set(worker.settings.worker_lock_key, "replacement")
                return dict(evaluated=1, enqueued=1, missed=0, skipped=0)

            callback = AsyncMock(side_effect=evaluate)
            monkeypatch.setitem(
                sys.modules, "cross_market.modules.alerts.application.schedules",
                SimpleNamespace(evaluate_schedules=callback),
            )
            if loss == "cancel":
                task = asyncio.create_task(
                    schedule_once(worker, session_factory=factory, calendar=object())
                )
                await asyncio.wait_for(entered.wait(), 2)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                with pytest.raises(OwnerLost):
                    await schedule_once(worker, session_factory=factory, calendar=object())
            if loss == "before":
                callback.assert_not_awaited()
        async with factory() as session:
            assert await session.scalar(select(func.count()).select_from(NotificationOutbox)) == 0
    finally:
        await engine.dispose()


@pytest.mark.parametrize("market", [True, False])
@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("calendar", [None, object()])
def test_schedule_registration_is_independent(market, enabled, calendar):
    tasks = registered_tasks(
        session_factory=object(), list_targets=object(), quote_service=object(), calendar=calendar,
        settings=Settings(market_observation_enabled=market, alert_observation_enabled=False,
                          schedule_reminders_enabled=enabled),
    )
    names = [task.func.__name__ for task in tasks]
    assert ("schedule_reminder" in names) == (enabled and calendar is not None)
    assert "notification_dispatcher" in names
    assert "alert_engine" not in names
    assert ("quote_collector" in names) == market


async def test_schedule_periodic_uses_configured_interval(monkeypatch):
    from cross_market.apps.worker import schedule_tasks

    periodic = AsyncMock()
    monkeypatch.setattr(schedule_tasks, "run_periodic", periodic)
    worker = SimpleNamespace(settings=Settings(schedule_scan_interval_seconds=7))
    await schedule_reminder(worker, session_factory=object(), calendar=object())
    assert periodic.await_args.kwargs["interval"] == 7
    assert periodic.await_args.kwargs["name"] == "schedule_reminder"


@pytest.mark.parametrize(
    ("result", "state", "code"),
    [
        (dict(evaluated=0, enqueued=0, missed=0, skipped=1), "partial", "CALENDAR_UNAVAILABLE"),
        (dict(evaluated=0, enqueued=0, missed=0, skipped=0), "idle", "NO_ENABLED_SCHEDULES"),
        (None, "error", "TASK_FAILED"),
    ],
)
async def test_schedule_periodic_publishes_accurate_safe_status(monkeypatch, result, state, code):
    from test_alert_worker import TransactionSession

    callback = AsyncMock(return_value=result)
    if result is None:
        callback.side_effect = RuntimeError("private secret")
    monkeypatch.setitem(
        sys.modules, "cross_market.modules.alerts.application.schedules",
        SimpleNamespace(evaluate_schedules=callback),
    )
    session = TransactionSession()
    async with FakeRedis(decode_responses=True) as redis:
        worker = WorkerRuntime(redis, Settings())
        await redis.set(worker.settings.worker_lock_key, worker.owner)
        original_eval = redis.eval

        async def stop_after_status(*args):
            written = await original_eval(*args)
            worker.stop_event.set()
            return written

        redis.eval = stop_after_status
        await schedule_reminder(worker, session_factory=session.factory, calendar=object())
        raw = await redis.get("health:worker:task:schedule_reminder")
        payload = json.loads(raw)
        assert payload["state"] == state and payload["detail"] == code
        assert payload["last_success_at"] is None and "secret" not in raw


@pytest.mark.parametrize("interval", [0, 31])
def test_schedule_interval_bounds(interval):
    with pytest.raises(ValueError):
        Settings(schedule_scan_interval_seconds=interval)


async def test_schedule_status_is_readonly_independent_and_hides_counts():
    redis = SimpleNamespace(get=AsyncMock(return_value=json.dumps({
        "state": "partial", "checked_at": datetime.now(UTC).isoformat(),
        "symbol_count": 999, "last_error": "private secret",
    })))
    settings = Settings(market_observation_enabled=False)
    tasks = await task_statuses(redis, settings)
    assert len(tasks) == 4
    schedule = tasks[-1]
    assert schedule.name == "schedule_reminder" and schedule.status == "partial"
    assert "日历不可用" in schedule.detail
    assert schedule.symbol_count is None and "secret" not in schedule.model_dump_json()
    assert redis.get.await_count == 2
    settings.schedule_reminders_enabled = False
    assert (await task_statuses(redis, settings))[-1].status == "disabled"


def test_schedule_migration_roundtrip_and_metadata(tmp_path):
    from pathlib import Path

    from alembic import command
    from alembic.autogenerate import compare_metadata
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from sqlalchemy import create_engine, inspect

    from cross_market.modules.alerts.infrastructure import schedule_models  # noqa: F401
    from cross_market.shared.database import Base

    backend = Path(__file__).resolve().parents[1]
    database = tmp_path / "schedule-migration.db"
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "migrations"))
    config.attributes["connection_url"] = f"sqlite+aiosqlite:///{database}"
    names = {"t_alert_schedule", "t_alert_schedule_run"}
    engine = create_engine(f"sqlite:///{database}")
    try:
        for _ in range(2):
            command.upgrade(config, "0007")
            with engine.connect() as connection:
                assert names <= set(inspect(connection).get_table_names())
                context = MigrationContext.configure(connection, opts={
                    "include_object": lambda obj, name, kind, reflected, compare_to: (
                        kind != "table" or name in names
                    ),
                })
                assert compare_metadata(context, Base.metadata) == []
            command.downgrade(config, "0006")
            with engine.connect() as connection:
                assert not names & set(inspect(connection).get_table_names())
                assert "t_alert_rule" in inspect(connection).get_table_names()
        command.upgrade(config, "0007")
    finally:
        engine.dispose()
