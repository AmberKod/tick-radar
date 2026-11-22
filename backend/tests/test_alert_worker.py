import asyncio
import json
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fakeredis.aioredis import FakeRedis

from cross_market.apps.worker.alert_tasks import (
    OwnerLost,
    dispatch_once,
    evaluate_once,
    run_periodic,
)
from cross_market.apps.worker.runtime import WorkerRuntime
from cross_market.apps.worker.task_registry import registered_tasks
from cross_market.shared.config import Settings


class TransactionSession:
    def __init__(self):
        self.committed = False
        self.rolled_back = False
        self.closed = False

    @asynccontextmanager
    async def begin(self):
        try:
            yield self
        except BaseException:
            self.rolled_back = True
            raise
        else:
            self.committed = True

    @asynccontextmanager
    async def factory(self):
        try:
            yield self
        finally:
            self.closed = True


@pytest.mark.parametrize("loss", ["before", "commit", "stop"])
async def test_dispatch_owner_loss_prevents_commit(monkeypatch, loss):
    session = TransactionSession()
    async with FakeRedis(decode_responses=True) as redis:
        worker = WorkerRuntime(redis, Settings())
        await redis.set(
            worker.settings.worker_lock_key, "other" if loss == "before" else worker.owner
        )

        async def dispatch(*args, **kwargs):
            if loss == "stop":
                worker.stop_event.set()
            else:
                await redis.set(worker.settings.worker_lock_key, "replacement")
            return dict(sent=1, failed=0, pending=0)

        callback = AsyncMock(side_effect=dispatch)
        monkeypatch.setitem(
            sys.modules,
            "cross_market.modules.notifications.application.service",
            SimpleNamespace(dispatch_pending=callback),
        )
        with pytest.raises(OwnerLost):
            await dispatch_once(worker, session_factory=session.factory)
        assert not session.committed and session.rolled_back and session.closed
        if loss == "before":
            callback.assert_not_awaited()


async def test_dispatch_cancellation_rolls_back_and_closes(monkeypatch):
    session = TransactionSession()
    entered = asyncio.Event()

    async def dispatch(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setitem(
        sys.modules,
        "cross_market.modules.notifications.application.service",
        SimpleNamespace(dispatch_pending=dispatch),
    )
    async with FakeRedis(decode_responses=True) as redis:
        worker = WorkerRuntime(redis, Settings())
        await redis.set(worker.settings.worker_lock_key, worker.owner)
        task = asyncio.create_task(dispatch_once(worker, session_factory=session.factory))
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert session.rolled_back and session.closed and not session.committed


async def test_alert_closes_target_session_before_snapshot_and_caps_symbols(monkeypatch):
    sessions = []

    @asynccontextmanager
    async def factory():
        session = TransactionSession()
        sessions.append(session)
        async with session.factory():
            yield session

    async def snapshot(symbols):
        assert sessions[0].closed and 0 < len(symbols) <= 50
        return SimpleNamespace(quotes=["cached"] if len(symbols) == 50 else [])

    evaluate = AsyncMock(return_value=dict(evaluated=1, triggered=0, skipped=2))
    monkeypatch.setitem(
        sys.modules,
        "cross_market.modules.alerts.application.service",
        SimpleNamespace(list_quote_targets=AsyncMock(return_value=[str(i) for i in range(60)])),
    )
    monkeypatch.setitem(
        sys.modules,
        "cross_market.modules.alerts.application.evaluation",
        SimpleNamespace(evaluate_rules=evaluate),
    )
    async with FakeRedis(decode_responses=True) as redis:
        worker = WorkerRuntime(redis, Settings())
        await redis.set(worker.settings.worker_lock_key, worker.owner)
        result = await evaluate_once(
            worker, session_factory=factory, quote_service=SimpleNamespace(snapshot=snapshot)
        )
        assert result[:3] == ("partial", 1, 2)
        assert sessions[1].committed and sessions[1].closed
        assert evaluate.await_args.args[1] == ["cached"]
        assert evaluate.await_args.args[2].utcoffset().total_seconds() == 0


async def test_alert_owner_loss_before_evaluation_commit_rolls_back(monkeypatch):
    sessions = []

    @asynccontextmanager
    async def factory():
        session = TransactionSession()
        sessions.append(session)
        async with session.factory():
            yield session

    async with FakeRedis(decode_responses=True) as redis:
        worker = WorkerRuntime(redis, Settings())
        await redis.set(worker.settings.worker_lock_key, worker.owner)

        async def evaluate(*args):
            await redis.set(worker.settings.worker_lock_key, "replacement")
            return dict(evaluated=1, triggered=1, skipped=0)

        monkeypatch.setitem(
            sys.modules,
            "cross_market.modules.alerts.application.service",
            SimpleNamespace(list_quote_targets=AsyncMock(return_value=["CN:600000"])),
        )
        monkeypatch.setitem(
            sys.modules,
            "cross_market.modules.alerts.application.evaluation",
            SimpleNamespace(evaluate_rules=evaluate),
        )
        with pytest.raises(OwnerLost):
            await evaluate_once(
                worker,
                session_factory=factory,
                quote_service=SimpleNamespace(
                    snapshot=AsyncMock(return_value=SimpleNamespace(quotes=[]))
                ),
            )
        assert sessions[1].rolled_back and sessions[1].closed and not sessions[1].committed


async def test_periodic_failure_diagnostics_hide_secrets_and_keep_last_success():
    async with FakeRedis(decode_responses=True) as redis:
        worker = WorkerRuntime(redis, Settings())
        await redis.set(worker.settings.worker_lock_key, worker.owner)
        key = "health:worker:task:notification_dispatcher"
        await redis.set(key, json.dumps({"last_success_at": "previous"}))
        original_eval = redis.eval

        async def stop(*args):
            result = await original_eval(*args)
            worker.stop_event.set()
            return result

        redis.eval = stop
        await run_periodic(
            worker,
            name="notification_dispatcher",
            interval=2,
            callback=AsyncMock(side_effect=RuntimeError("password=secret")),
        )
        raw = await redis.get(key)
        assert "secret" not in raw
        assert json.loads(raw)["detail"] == "TASK_FAILED"
        assert json.loads(raw)["last_success_at"] == "previous"


def test_market_disabled_keeps_notification_task():
    tasks = registered_tasks(
        session_factory=object(),
        list_targets=object(),
        quote_service=object(),
        settings=Settings(market_observation_enabled=False),
    )
    assert [task.func.__name__ for task in tasks] == ["notification_dispatcher"]


async def test_collection_targets_keep_priority_and_cap(monkeypatch):
    from cross_market.apps.worker import main
    from cross_market.apps.worker.main import list_collection_targets

    monkeypatch.setattr(main, "_alert_collection_offset", 0)
    monkeypatch.setitem(
        sys.modules,
        "cross_market.modules.portfolio.application.summary",
        SimpleNamespace(list_quote_targets=AsyncMock(return_value=[str(i) for i in range(30)])),
    )
    monkeypatch.setitem(
        sys.modules,
        "cross_market.modules.watchlist.application.service",
        SimpleNamespace(list_quote_targets=AsyncMock(return_value=[str(i) for i in range(20, 45)])),
    )
    monkeypatch.setitem(
        sys.modules,
        "cross_market.modules.alerts.application.service",
        SimpleNamespace(list_quote_targets=AsyncMock(return_value=[str(i) for i in range(40, 70)])),
    )
    assert await list_collection_targets(object()) == [str(i) for i in range(50)]
    second = await list_collection_targets(object())
    assert second[:40] == [str(i) for i in range(40)]
    assert second[40:] == [str(i) for i in range(50, 60)]


async def test_collection_rotation_includes_truncated_holding_alert(monkeypatch):
    from cross_market.apps.worker import main

    monkeypatch.setattr(main, "_alert_collection_offset", 0)
    for module, symbols in (
        ("portfolio.application.summary", [f"A{i}" for i in range(50)]),
        ("watchlist.application.service", []),
        ("alerts.application.service", ["A49", "B"]),
    ):
        monkeypatch.setitem(sys.modules, f"cross_market.modules.{module}",
                            SimpleNamespace(list_quote_targets=AsyncMock(return_value=symbols)))
    result = await main.list_collection_targets(object())
    assert len(result) == 50 and "A49" in result and "B" in result


async def test_real_notification_transaction_rolls_back_delivery_on_owner_loss(tmp_path):
    from uuid import uuid4

    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from cross_market.modules.notifications.application.service import enqueue
    from cross_market.modules.notifications.infrastructure.models import (
        InboxMessage,
        NotificationDelivery,
        NotificationOutbox,
    )
    from cross_market.shared.database import Base

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'notification.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda conn: Base.metadata.create_all(
                    conn,
                    tables=[
                        NotificationOutbox.__table__,
                        NotificationDelivery.__table__,
                        InboxMessage.__table__,
                    ],
                )
            )
        async with factory.begin() as session:
            await enqueue(session, str(uuid4()), "测试", "站内通知", {})
        async with FakeRedis(decode_responses=True) as redis:
            worker = WorkerRuntime(redis, Settings())
            await redis.set(worker.settings.worker_lock_key, worker.owner)
            original_get = redis.get
            calls = 0

            async def lose_at_commit(key):
                nonlocal calls
                calls += 1
                return await original_get(key) if calls == 1 else "replacement"

            redis.get = lose_at_commit
            with pytest.raises(OwnerLost):
                await dispatch_once(worker, session_factory=factory)
        async with factory() as session:
            assert await session.scalar(select(func.count()).select_from(InboxMessage)) == 0
            assert await session.scalar(select(func.count()).select_from(NotificationDelivery)) == 0
            outbox = await session.scalar(select(NotificationOutbox))
            assert outbox.status == "PENDING" and outbox.attempts == 0
    finally:
        await engine.dispose()


def test_migration_schema_matches_alert_notification_models(tmp_path):
    from pathlib import Path

    from alembic import command
    from alembic.autogenerate import compare_metadata
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from sqlalchemy import create_engine

    from cross_market.shared.database import Base

    backend = Path(__file__).resolve().parents[1]
    database = tmp_path / "migration.db"
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "migrations"))
    config.attributes["connection_url"] = f"sqlite+aiosqlite:///{database}"
    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{database}")
    names = {
        "t_alert_rule",
        "t_alert_rule_state",
        "t_alert_log",
        "t_alert_outbox",
        "t_alert_delivery",
        "t_notification_inbox",
    }
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection,
                opts={
                    "include_object": lambda obj, name, kind, reflected, compare_to: (
                        kind != "table" or name in names
                    ),
                },
            )
            assert compare_metadata(context, Base.metadata) == []
        command.downgrade(config, "0005")
        command.upgrade(config, "head")
    finally:
        engine.dispose()
