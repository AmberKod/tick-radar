import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import fakeredis.aioredis
import httpx
import pytest

from cross_market.apps.api.main import create_app
from cross_market.modules.market_data.application.schemas import QuoteDTO
from cross_market.modules.market_data.application.service import QuoteService
from cross_market.modules.market_data.application.stream import QuoteStreamService
from cross_market.modules.market_data.infrastructure.cache import QUOTE_CHANNEL
from cross_market.modules.market_data.infrastructure.events import RedisQuoteEvents
from cross_market.shared.config import Settings
from cross_market.shared.exceptions import AppError

SYMBOL = "CN:600519"


def make_quote(**changes):
    return QuoteDTO(
        symbol=SYMBOL,
        name="测试报价",
        market="CN",
        currency="CNY",
        provider_symbol="sh600519",
        price="10.01",
        quality_status="UNKNOWN",
        received_at=datetime.now(UTC),
        **changes,
    )


async def disconnected():
    return False


async def service(redis, **kwargs):
    quotes = QuoteService(None, redis, Settings())
    quotes.source.fetch = AsyncMock(side_effect=AssertionError("SSE不允许取供应商数据"))
    return QuoteStreamService(quotes, RedisQuoteEvents(redis), **kwargs)


async def next_kind(events, kind):
    async with asyncio.timeout(2):
        while True:
            event = await anext(events)
            if event.event == kind:
                return event


async def test_subscribe_snapshot_publish_two_clients_without_provider_requests():
    async with fakeredis.aioredis.FakeRedis(decode_responses=True) as redis:
        stream = await service(redis)
        original = make_quote()
        await stream.quotes.cache.write(SYMBOL, original.model_dump_json())
        sessions = [await stream.open([SYMBOL]) for _ in range(2)]
        events = [session.events(disconnected) for session in sessions]
        try:
            first = [await anext(source) for source in events]
            assert all(event.event == "snapshot" for event in first)
            assert all(event.quotes[0].price == original.price for event in first)
            assert all(event.schema_version == 1 for event in first)
            assert len({event.id for event in first}) == 2
            owner = await stream.quotes.cache.acquire(SYMBOL)
            changed = original.model_copy(update={"price": "11.02"})
            assert await stream.quotes.cache.write(SYMBOL, changed.model_dump_json(), owner=owner)
            updated = [await next_kind(source, "quote.updated") for source in events]
            assert all(event.quotes[0].price == "11.02" for event in updated)
            assert all(event.symbols == [SYMBOL] for event in updated)
            stream.quotes.source.fetch.assert_not_awaited()
        finally:
            for source in events:
                await source.aclose()
        assert len(stream.active) == 0
        assert await redis.pubsub_numsub(QUOTE_CHANNEL) == [(QUOTE_CHANNEL, 0)]


async def test_notifications_are_fenced_with_symbol_and_worker_owner():
    async with fakeredis.aioredis.FakeRedis(decode_responses=True) as redis:
        stream = await service(redis)
        session = await stream.open([SYMBOL])
        events = session.events(disconnected)
        try:
            first = await anext(events)
            assert first.quotes[0].error.code == "CACHE_PENDING"
            owner = await stream.quotes.cache.acquire(SYMBOL)
            await redis.set("worker:test", "replacement")
            assert not await stream.quotes.cache.write(
                SYMBOL,
                make_quote().model_dump_json(),
                owner=owner,
                publication_guard=("worker:test", "old"),
            )
            assert await redis.get("market:quote:" + SYMBOL) is None
            assert (
                await session.subscription.get_message(ignore_subscribe_messages=True, timeout=0.01)
                is None
            )
            await redis.set("worker:test", "old")
            assert await stream.quotes.cache.write(
                SYMBOL,
                make_quote().model_dump_json(),
                owner=owner,
                publication_guard=("worker:test", "old"),
            )
            assert (await next_kind(events, "quote.updated")).quotes[0].price == "10.01"
        finally:
            await events.aclose()


async def test_subscribe_before_snapshot_covers_opening_race_and_reconnect():
    async with fakeredis.aioredis.FakeRedis(decode_responses=True) as redis:
        stream = await service(redis)
        original = stream.quotes.snapshot

        async def write_during_snapshot(symbols):
            # 订阅已确认，初始快照读取前发生的发布也必须被快照包含。
            assert await redis.pubsub_numsub(QUOTE_CHANNEL) == [(QUOTE_CHANNEL, 1)]
            owner = await stream.quotes.cache.acquire(SYMBOL)
            await stream.quotes.cache.write(SYMBOL, make_quote().model_dump_json(), owner=owner)
            return await original(symbols)

        stream.quotes.snapshot = write_during_snapshot
        first = await stream.open([SYMBOL])
        source = first.events(disconnected)
        assert (await anext(source)).quotes[0].price == "10.01"
        await source.aclose()
        # 离线发布不重放；重新订阅从最新全量恢复。
        await stream.quotes.cache.write(
            SYMBOL, make_quote().model_copy(update={"price": "12.34"}).model_dump_json()
        )
        stream.quotes.snapshot = original
        second = await stream.open([SYMBOL])
        source = second.events(disconnected)
        restored = await anext(source)
        assert restored.event == "snapshot"
        assert restored.quotes[0].price == "12.34"
        await source.aclose()


async def test_heartbeat_resyncs_quality_and_cannot_keep_old_cache_fresh():
    async with fakeredis.aioredis.FakeRedis(decode_responses=True) as redis:
        stream = await service(redis, heartbeat_interval=0.001, read_interval=0.002)
        original = make_quote()
        await stream.quotes.cache.write(SYMBOL, original.model_dump_json())
        session = await stream.open([SYMBOL])
        source = session.events(disconnected)
        try:
            await anext(source)
            beat = await next_kind(source, "heartbeat")
            assert beat.quotes == []
            old = original.model_copy(
                update={"received_at": datetime.now(UTC) - timedelta(seconds=181)}
            )
            await stream.quotes.cache.write(SYMBOL, old.model_dump_json())
            stale = await next_kind(source, "quote.updated")
            assert stale.quotes[0].quality_status == "STALE"
            assert stale.quotes[0].received_at == old.received_at
        finally:
            await source.aclose()


async def test_stream_failure_redacted_and_closes_subscription():
    async with fakeredis.aioredis.FakeRedis(decode_responses=True) as redis:
        stream = await service(redis, heartbeat_interval=0.001, read_interval=0.002)
        session = await stream.open([SYMBOL])
        source = session.events(disconnected)
        await anext(source)
        session.subscription.get_message = AsyncMock(
            side_effect=ConnectionError("redis://password@private-host")
        )
        failure = await anext(source)
        assert failure.event == "error"
        assert failure.error.code == "STREAM_UNAVAILABLE"
        assert "password" not in failure.model_dump_json()
        with pytest.raises(StopAsyncIteration):
            await anext(source)
        assert not stream.active


async def test_connection_limit_opening_failure_disconnect_and_shutdown_cleanup():
    async with fakeredis.aioredis.FakeRedis(decode_responses=True) as redis:
        stream = await service(redis, max_connections=1)
        session = await stream.open([SYMBOL])
        with pytest.raises(AppError) as limit:
            await stream.open([SYMBOL])
        assert limit.value.status == 429
        source = session.events(AsyncMock(return_value=True))
        await anext(source)
        with pytest.raises(StopAsyncIteration):
            await anext(source)
        assert not stream.active
        await stream.open([SYMBOL])
        await stream.close()
        assert not stream.active
        assert await redis.pubsub_numsub(QUOTE_CHANNEL) == [(QUOTE_CHANNEL, 0)]
        stream.quotes.snapshot = AsyncMock(side_effect=ConnectionError("private"))
        with pytest.raises(AppError) as unavailable:
            await stream.open([SYMBOL])
        assert unavailable.value.code == "STREAM_UNAVAILABLE"
        assert stream._opening == 0
        assert await redis.pubsub_numsub(QUOTE_CHANNEL) == [(QUOTE_CHANNEL, 0)]


async def test_stream_auth_validation_and_open_failure_before_response_headers():
    app = create_app(Settings(api_token="test-token"))
    app.state.quote_stream = SimpleNamespace(
        open=AsyncMock(side_effect=AppError(503, "STREAM_UNAVAILABLE", "共享报价不可用"))
    )
    transport = httpx.ASGITransport(app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/api/v1/events/stream?symbols=" + SYMBOL)).status_code == 401
        assert (
            await client.get("/api/v1/events/stream?symbols=" + SYMBOL + "&token=test-token")
        ).status_code == 401
        headers = {"Authorization": "Bearer test-token"}
        for invalid in ["", "US:AAPL?", ",".join([SYMBOL] * 51)]:
            assert (
                await client.get(
                    "/api/v1/events/stream", params={"symbols": invalid}, headers=headers
                )
            ).status_code == 422
        response = await client.get(
            "/api/v1/events/stream", params={"symbols": SYMBOL}, headers=headers
        )
        assert response.status_code == 503
        assert response.json()["code"] == "STREAM_UNAVAILABLE"
        app.state.quote_stream.open.assert_awaited_once_with([SYMBOL])
        schema = app.openapi()
        assert "QuoteStreamEvent" in schema["components"]["schemas"]
        content = schema["paths"]["/api/v1/events/stream"]["get"]["responses"]["200"]["content"]
        assert "text/event-stream" in content


@pytest.mark.parametrize("phase", ["headers", "first_body"])
async def test_response_send_failure_releases_stream_even_before_first_frame(phase):
    from starlette.requests import ClientDisconnect

    from cross_market.modules.market_data.interfaces.events import QuoteStreamingResponse

    async with fakeredis.aioredis.FakeRedis(decode_responses=True) as redis:
        stream = await service(redis)
        session = await stream.open([SYMBOL])

        async def frames():
            async for event in session.events(disconnected):
                yield event.model_dump_json()

        response = QuoteStreamingResponse(frames(), session=session)

        async def send(message):
            expected = "http.response.start" if phase == "headers" else "http.response.body"
            if message["type"] == expected:
                raise OSError("client disconnected")

        with pytest.raises(ClientDisconnect):
            await response({"type": "http", "asgi": {"spec_version": "2.4"}}, None, send)
        assert not stream.active
        assert await redis.pubsub_numsub(QUOTE_CHANNEL) == [(QUOTE_CHANNEL, 0)]


async def test_asgi_cancel_scope_cleanup_releases_redis_subscription():
    import anyio

    async with fakeredis.aioredis.FakeRedis(decode_responses=True) as redis:
        stream = await service(redis)
        session = await stream.open([SYMBOL])
        with anyio.CancelScope() as scope:
            scope.cancel()
            await session.close()
        assert not stream.active
        assert await redis.pubsub_numsub(QUOTE_CHANNEL) == [(QUOTE_CHANNEL, 0)]
