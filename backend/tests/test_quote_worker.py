import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fakeredis.aioredis import FakeRedis

from cross_market.apps.worker.quote_collector import TASK_KEY, quote_collector
from cross_market.apps.worker.runtime import WorkerRuntime
from cross_market.apps.worker.task_registry import registered_tasks
from cross_market.shared.config import Settings


def settings(**overrides):
    values = Settings().model_dump()
    values.update(
        market_observation_enabled=True,
        quote_refresh_interval_seconds=0.01,
        quote_max_symbols=50,
        worker_heartbeat_interval_seconds=0.01,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


@asynccontextmanager
async def session_factory():
    yield object()


def quote(symbol="CN:600000", **overrides):
    values = dict(symbol=symbol, price="10", error=None, quality_status="UNKNOWN")
    values.update(overrides)
    return SimpleNamespace(**values)


async def run_round(redis, worker, targets, quotes):
    service = SimpleNamespace(get_quotes=AsyncMock(return_value=SimpleNamespace(quotes=quotes)))
    listed = AsyncMock(return_value=targets)
    worker.stop_event.clear()
    original_eval = redis.eval

    async def eval_and_stop(*args):
        result = await original_eval(*args)
        worker.stop_event.set()
        return result

    redis.eval = eval_and_stop
    try:
        await quote_collector(
            worker, session_factory=session_factory, list_targets=listed, quote_service=service
        )
    finally:
        redis.eval = original_eval
    return json.loads(await redis.get(TASK_KEY)), service


async def test_empty_targets_idle_then_success_then_partial_preserves_success():
    async with FakeRedis(decode_responses=True) as redis:
        worker = WorkerRuntime(redis, settings())
        await redis.set(worker.settings.worker_lock_key, worker.owner)
        payload, service = await run_round(redis, worker, [], [])
        assert payload["state"] == "idle"
        assert payload["last_success_at"] is None
        service.get_quotes.assert_not_awaited()
        payload, service = await run_round(redis, worker, ["CN:600000"], [quote()])
        assert payload["state"] == "success"
        last_success = payload["last_success_at"]
        assert last_success
        service.get_quotes.assert_awaited_once_with(
            ["CN:600000"],
            refresh=True,
            publication_guard=(worker.settings.worker_lock_key, worker.owner),
        )
        payload, _ = await run_round(
            redis, worker, ["CN:600000"], [quote(error=SimpleNamespace(code="UPSTREAM"))]
        )
        assert payload["state"] == "partial"
        assert payload["error_count"] == 1
        assert payload["last_success_at"] == last_success
        payload, _ = await run_round(redis, worker, [], [])
        assert payload["last_success_at"] == last_success
        assert 0 < await redis.ttl(TASK_KEY) <= 120


@pytest.mark.parametrize("price", [None, "0", "-1", "NaN", "Infinity", "wrong"])
async def test_invalid_prices_never_succeed(price):
    async with FakeRedis(decode_responses=True) as redis:
        worker = WorkerRuntime(redis, settings())
        await redis.set(worker.settings.worker_lock_key, worker.owner)
        payload, _ = await run_round(redis, worker, ["CN:600000"], [quote(price=price)])
        assert payload["state"] == "partial"
        assert payload["last_success_at"] is None


async def test_stale_and_missing_quotes_are_partial():
    async with FakeRedis(decode_responses=True) as redis:
        worker = WorkerRuntime(redis, settings())
        await redis.set(worker.settings.worker_lock_key, worker.owner)
        payload, _ = await run_round(
            redis, worker, ["CN:600000", "HK:00700"], [quote(quality_status="STALE")]
        )
        assert payload["error_count"] == 2
        assert payload["state"] == "partial"


async def test_status_write_is_owner_fenced():
    async with FakeRedis(decode_responses=True) as redis:
        worker = WorkerRuntime(redis, settings())
        await redis.set(worker.settings.worker_lock_key, "replacement")
        await redis.set(TASK_KEY, "replacement-status")
        with pytest.raises(RuntimeError, match="所有权"):
            await run_round(redis, worker, [], [])
        assert await redis.get(TASK_KEY) == "replacement-status"


async def test_callback_failure_retries_without_leaking_secrets():
    async with FakeRedis(decode_responses=True) as redis:
        worker = WorkerRuntime(redis, settings())
        await redis.set(worker.settings.worker_lock_key, worker.owner)
        seen = []
        original_eval = redis.eval

        async def capture(*args):
            result = await original_eval(*args)
            seen.append(json.loads(await redis.get(TASK_KEY)))
            if len(seen) == 2:
                worker.stop_event.set()
            return result

        redis.eval = capture
        listed = AsyncMock(side_effect=[RuntimeError("password=secret-value"), []])
        await asyncio.wait_for(
            quote_collector(
                worker, session_factory=session_factory, list_targets=listed, quote_service=None
            ),
            1,
        )
        assert [item["state"] for item in seen] == ["error", "idle"]
        assert seen[0]["detail"] == "COLLECTION_FAILED"
        assert "secret-value" not in json.dumps(seen)


async def test_slow_query_has_deadline_and_closes_session():
    async with FakeRedis(decode_responses=True) as redis:
        worker = WorkerRuntime(redis, settings())
        await redis.set(worker.settings.worker_lock_key, worker.owner)
        closed = asyncio.Event()

        @asynccontextmanager
        async def tracked_session():
            try:
                yield object()
            finally:
                closed.set()

        async def slow(*args, **kwargs):
            await asyncio.Event().wait()

        original_eval = redis.eval

        async def stop(*args):
            result = await original_eval(*args)
            worker.stop_event.set()
            return result

        redis.eval = stop
        await asyncio.wait_for(
            quote_collector(
                worker, session_factory=tracked_session, list_targets=slow, quote_service=None
            ),
            1,
        )
        payload = json.loads(await redis.get(TASK_KEY))
        assert payload["state"] == "error"
        assert payload["detail"] == "COLLECTION_TIMEOUT"
        assert closed.is_set()


async def test_tasks_start_only_after_initial_renew_and_cancel_before_release():
    async with FakeRedis(decode_responses=True) as redis:
        entered = asyncio.Event()
        cancelled = asyncio.Event()
        worker = None

        async def callback(runtime):
            assert await redis.get(runtime.settings.worker_lock_key) == runtime.owner
            assert await redis.get(runtime.settings.worker_heartbeat_key)
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        worker = WorkerRuntime(redis, settings(), tasks=[callback])
        original_release = worker.release

        async def release():
            assert cancelled.is_set()
            await original_release()

        worker.release = release
        task = asyncio.create_task(worker.run())
        await asyncio.wait_for(entered.wait(), 1)
        # callback 阻塞时，心跳仍持续续租。
        renewed = asyncio.Event()
        original_renew = worker.renew

        async def track_renew():
            result = await original_renew()
            renewed.set()
            return result

        worker.renew = track_renew
        await asyncio.wait_for(renewed.wait(), 1)
        assert json.loads(await redis.get(worker.settings.worker_heartbeat_key))["tasks_enabled"]
        await redis.set(worker.settings.worker_lock_key, "replacement")
        assert await asyncio.wait_for(task, 1) == 1
        assert cancelled.is_set()
        assert await redis.get(worker.settings.worker_lock_key) == "replacement"


async def test_contender_and_initial_renew_failure_do_not_start_tasks():
    async with FakeRedis(decode_responses=True) as redis:
        callback = AsyncMock()
        worker = WorkerRuntime(redis, settings(), tasks=[callback])
        await redis.set(worker.settings.worker_lock_key, "other")
        assert await worker.run() == 1
        callback.assert_not_called()
        await redis.delete(worker.settings.worker_lock_key)
        worker.renew = AsyncMock(return_value=False)
        assert await worker.run() == 1
        callback.assert_not_called()


async def test_redis_failure_cancels_callbacks():
    async with FakeRedis(decode_responses=True) as redis:
        entered = asyncio.Event()
        cancelled = asyncio.Event()

        async def callback(runtime):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        worker = WorkerRuntime(redis, settings(), tasks=[callback])
        original_renew = worker.renew

        async def renew():
            if entered.is_set():
                raise ConnectionError("unavailable")
            return await original_renew()

        worker.renew = renew
        with pytest.raises(ConnectionError):
            await asyncio.wait_for(worker.run(), 1)
        assert cancelled.is_set()


@pytest.mark.parametrize("failure", [False, True])
async def test_main_closes_all_resources_without_real_database(monkeypatch, failure):
    from cross_market.apps.worker import main

    redis = SimpleNamespace(aclose=AsyncMock())
    engine = SimpleNamespace(dispose=AsyncMock())
    client = SimpleNamespace(aclose=AsyncMock())

    @asynccontextmanager
    async def client_context(**kwargs):
        try:
            yield client
        finally:
            await client.aclose()

    monkeypatch.setattr(main, "Settings", settings)
    monkeypatch.setattr(main.Redis, "from_url", lambda *a, **k: redis)
    monkeypatch.setattr(main, "create_engine", lambda *a: engine)
    monkeypatch.setattr(main, "async_sessionmaker", lambda *a, **k: session_factory)
    monkeypatch.setattr(main.httpx, "AsyncClient", client_context)
    monkeypatch.setattr(main.signal, "signal", lambda *a: None)

    async def run(runtime):
        assert len(runtime.tasks) == 1
        if failure:
            raise RuntimeError("password=secret-value")
        return 0

    monkeypatch.setattr(main.WorkerRuntime, "run", run)
    assert await main.run() == int(failure)
    client.aclose.assert_awaited_once()
    engine.dispose.assert_awaited_once()
    redis.aclose.assert_awaited_once()


def test_registry_defaults_empty_and_registers_one_callback():
    assert registered_tasks() == ()
    assert (
        len(
            registered_tasks(
                session_factory=session_factory, list_targets=AsyncMock(), quote_service=object()
            )
        )
        == 1
    )
