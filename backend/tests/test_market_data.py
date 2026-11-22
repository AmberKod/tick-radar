import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import fakeredis.aioredis
import httpx
import pytest
from fastapi.testclient import TestClient

from cross_market.apps.api.main import create_app
from cross_market.modules.market_data.application.schemas import QuoteDTO
from cross_market.modules.market_data.application.service import QuoteService
from cross_market.modules.market_data.domain.quotes import (
    market_status,
    parse_record,
    provider_symbol,
)
from cross_market.modules.market_data.infrastructure.tencent import ProviderFailure, TencentSource
from cross_market.modules.securities.application.schemas import SecurityFromQuote
from cross_market.shared.config import Settings


def record(key="sh600519", ticker="600519", market="1", price="12.345", previous="10.001"):
    parts = [""] * 31
    parts[0:5] = [market, "测试证券", ticker, price, previous]
    parts[6] = "100"
    parts[30] = "20261120150000"
    return f'v_{key}="{"~".join(parts)}";'


@pytest.mark.parametrize(
    "symbol,key,ticker,market",
    [
        ("CN:600519", "sh600519", "600519", "1"),
        ("CN:510300", "sh510300", "510300", "51"),
        ("CN:159915", "sz159915", "159915", "51"),
        ("HK:00700", "hk00700", "00700", "100"),
        ("US:AAPL", "usAAPL", "AAPL.OQ", "200"),
        ("US:BRK.B", "usBRK.B", "BRK.B.N", "200"),
    ],
)
async def test_markets_exact_decimal_and_timestamp(symbol, key, ticker, market):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, content=record(key, ticker, market).encode("gb18030")
            )
        )
    ) as client:
        service = QuoteService(client, fakeredis.aioredis.FakeRedis(), Settings())
        quote = (await service.get_quotes([symbol])).quotes[0]
        assert quote.price == "12.345"
        assert quote.change == "2.344"
        assert quote.change_percent == "23.4377"
        assert quote.delay_status == "UNKNOWN"
        assert quote.error is None
        assert quote.provider_symbol == key
        if symbol.startswith("US:"):
            assert quote.market_timestamp is None
            assert quote.timestamp_timezone_basis == "UNVERIFIED"
        else:
            assert quote.market_timestamp == datetime(2026, 11, 20, 7, tzinfo=UTC)


async def test_record_isolation_and_batch_keys():
    payload = record() + record("hk00700", "99999", "100")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=payload.encode("gb18030"))
        )
    ) as client:
        service = QuoteService(client, fakeredis.aioredis.FakeRedis(), Settings())
        result = await service.get_quotes(["CN:600519", "HK:00700", "US:NOTFOUND"])
        assert result.quotes[0].price == "12.345"
        assert result.quotes[1].quality_status == "INVALID"
        assert result.quotes[2].quality_status == "UNAVAILABLE"


async def test_cache_gate_concurrency_and_failed_refresh_preserves_timestamp():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) > 1:
            return httpx.Response(429)
        return httpx.Response(200, content=record().encode("gb18030"))

    redis = fakeredis.aioredis.FakeRedis()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = QuoteService(client, redis, Settings())
        first = (await service.get_quotes(["CN:600519"])).quotes[0]
        await asyncio.gather(*(service.get_quotes(["CN:600519"], True) for _ in range(10)))
        await service.get_quotes(["CN:600519"])
        assert len(calls) == 1
        await redis.delete("market:refresh:CN:600519")
        service._attempts.clear()
        failed = (await service.get_quotes(["CN:600519"], True)).quotes[0]
        assert failed.received_at == first.received_at
        assert failed.price == first.price
        assert failed.quality_status == "STALE"
        assert failed.error.code == "PROVIDER_RATE_LIMIT"
        assert (await service.get_quotes(["CN:600519"])).quotes[0].quality_status == "STALE"
        failed.attempted_at -= timedelta(seconds=16)
        await service.cache.write(failed.symbol, failed.model_dump_json())
        await redis.delete("market:refresh:CN:600519")
        service._attempts.clear()
        service.source.fetch = AsyncMock(
            return_value=({"sh600519": "1~名称~600519~15~10"}, datetime.now(UTC))
        )
        recovered = (await service.get_quotes([failed.symbol])).quotes[0]
        assert recovered.price == "15"
        assert recovered.error is None
        assert recovered.received_at > first.received_at


async def test_distributed_gate_between_services():
    calls = []

    async def handler(request):
        calls.append(request)
        await asyncio.sleep(0)
        return httpx.Response(200, content=record().encode("gb18030"))

    redis = fakeredis.aioredis.FakeRedis()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        services = [QuoteService(client, redis, Settings()) for _ in range(5)]
        await asyncio.gather(*(s.get_quotes(["CN:600519"], True) for s in services))
        assert len(calls) == 1


async def test_broken_cache_and_disabled():
    redis = SimpleNamespace(
        get=AsyncMock(side_effect=ConnectionError), set=AsyncMock(side_effect=ConnectionError)
    )
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=record().encode("gb18030"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = QuoteService(client, redis, Settings())
        quote = (await service.get_quotes(["CN:600519"])).quotes[0]
        assert quote.price
        assert any("缓存不可用" in warning for warning in quote.warnings)
        await service.get_quotes(["CN:600519"], True)
        assert len(calls) == 1
        service.settings = Settings(market_observation_enabled=False)
        assert (await service.get_quotes(["CN:600519"])).quotes[
            0
        ].error.code == "OBSERVATION_DISABLED"
        assert len(calls) == 1


@pytest.mark.parametrize(
    "failure,code",
    [
        (httpx.ReadTimeout("timeout"), "PROVIDER_TIMEOUT"),
        (httpx.ConnectError("private"), "PROVIDER_UNAVAILABLE"),
    ],
)
async def test_network_failures(failure, code):
    def handler(request):
        raise failure

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        quote = (
            await QuoteService(client, fakeredis.aioredis.FakeRedis(), Settings()).get_quotes(
                ["CN:600519"]
            )
        ).quotes[0]
        assert quote.error.code == code
        assert quote.received_at is None


async def test_body_limit():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b"x" * (256 * 1024 + 1))
        )
    ) as client:
        with pytest.raises(ProviderFailure) as failure:
            await TencentSource(client).fetch(["US:AAPL"])
        assert failure.value.code == "PROVIDER_BODY_TOO_LARGE"


async def test_dynamic_cache_age_overrides_weekend():
    now = datetime.now(UTC)
    quote = QuoteDTO(
        symbol="CN:600519",
        market="CN",
        currency="CNY",
        provider_symbol="sh600519",
        price="10",
        received_at=now - timedelta(seconds=181),
    )
    redis = fakeredis.aioredis.FakeRedis()
    await redis.set("market:quote:CN:600519", quote.model_dump_json())
    await redis.set("market:refresh:CN:600519", "active-owner", ex=15)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: pytest.fail())
    ) as client:
        result = (await QuoteService(client, redis, Settings()).get_quotes([quote.symbol])).quotes[
            0
        ]
        assert result.quality_status == "STALE"
        assert result.cache_age_seconds >= 181
    assert market_status("CN", datetime(2026, 11, 22, tzinfo=UTC)) == "MARKET_CLOSED"
    assert market_status("US", datetime(2026, 11, 20, 18, tzinfo=UTC)) == "UNKNOWN"


def test_partial_time_and_invalid_prices():
    assert parse_record("CN:600519", "1~名称~600519~1.001~1.000")["market_timestamp"] is None
    assert parse_record("CN:600519", "1~名称~600519~1~1")["provider_exchange"] == "SSE"
    assert parse_record("HK:00700", "100~名称~00700~1~1")["provider_exchange"] == "HKEX"
    for suffix, exchange in [(".OQ", "NASDAQ"), (".N", "NYSE"), (".A", "AMEX"), ("", None)]:
        fields = parse_record("US:AAPL", f"200~名称~AAPL{suffix}~1~1")
        assert fields["provider_exchange"] == exchange
    with pytest.raises(ValueError, match="标识"):
        parse_record("US:AAPL", "200~名称~AAPL.UNKNOWN~1~1")
    for price in ["NaN", "Infinity", "0", "-1", "1e999", "9" * 17]:
        with pytest.raises(ValueError):
            parse_record("CN:600519", f"1~名称~600519~{price}~1")
    for symbol in ["CN:123456", "HK:700", "US:AAPL?", "US:" + "A" * 21]:
        with pytest.raises(ValueError):
            provider_symbol(symbol)


def test_public_get_and_authenticated_refresh_validation():
    app = create_app(Settings(api_token="test-token"))
    quote = QuoteService.empty("US:AAPL", "TEST", "测试")
    app.state.quote_service = SimpleNamespace(
        get_quotes=AsyncMock(
            return_value=SimpleNamespace(
                quotes=[quote], checked_at=datetime.now(UTC), observation_only=True
            )
        )
    )
    from cross_market.shared.database import get_session

    async def fake_session():
        yield None

    app.dependency_overrides[get_session] = fake_session
    with TestClient(app, raise_server_exceptions=True) as client:
        # lifespan建立真实资源后替换服务，测试不发送网络请求。
        app.state.quote_service = SimpleNamespace(
            get_quotes=AsyncMock(
                return_value=SimpleNamespace(
                    quotes=[quote], checked_at=datetime.now(UTC), observation_only=True
                )
            )
        )
        assert client.get("/api/v1/market/quote?symbol=US:AAPL").status_code == 200
        for endpoint in ["quote?symbol=US:AAPL", "quotes?symbols=US:AAPL"]:
            response = client.get(f"/api/v1/market/{endpoint}&refresh=true")
            assert response.status_code == 422
            assert "REFRESH_REQUIRES_POST" in response.text
        headers = {"Authorization": "Bearer test-token"}
        assert (
            client.get(
                "/api/v1/market/quote?symbol=US:AAPL&refresh=true", headers=headers
            ).status_code
            == 422
        )
        assert (
            client.post("/api/v1/market/refresh", json={"symbols": ["US:AAPL"]}).status_code == 401
        )
        headers = {"Authorization": "Bearer test-token"}
        assert (
            client.post(
                "/api/v1/market/refresh", headers=headers, json={"symbols": ["bad"]}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/v1/securities/from-quote", headers=headers, json={"symbol": "US:AAPL"}
            ).status_code
            == 422
        )


def test_from_quote_identity_validation():
    assert SecurityFromQuote(symbol="US:AAPL", exchange="NASDAQ").exchange == "NASDAQ"
    assert SecurityFromQuote(symbol="CN:510300", security_type="ETF").security_type == "ETF"
    for body in [
        {"symbol": "US:AAPL"},
        {"symbol": "CN:600519", "exchange": "SZSE"},
        {"symbol": "CN:510300"},
        {"symbol": "HK:00700", "exchange": "NYSE"},
        {"symbol": "HK:80700", "exchange": "HKEX"},
        {"symbol": "HK:90700", "exchange": "HKEX"},
    ]:
        with pytest.raises(ValueError):
            SecurityFromQuote(**body)


@pytest.mark.parametrize("symbol", ["HK:80700", "HK:90700", "HK:10000"])
def test_only_hkd_counter_supported(symbol):
    with pytest.raises(ValueError):
        provider_symbol(symbol)
    with pytest.raises(ValueError):
        parse_record(symbol, f"100~名称~{symbol[3:]}~10~9")


@pytest.mark.parametrize("currency", ["USD", "CNY", "RMB"])
def test_explicit_currency_mismatch(currency):
    with pytest.raises(ValueError, match="币种"):
        parse_record("HK:00700", f"100~名称~00700~10~9~{currency}")
    assert parse_record("HK:00700", "100~名称~00700~10~9~HKD")["price"] == "10"


async def test_negative_cache_expires_and_get_recovers():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return (
            httpx.Response(503)
            if calls == 1
            else httpx.Response(200, content=record().encode("gb18030"))
        )

    redis = fakeredis.aioredis.FakeRedis()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = QuoteService(client, redis, Settings())
        failed = (await service.get_quotes(["CN:600519"])).quotes[0]
        assert failed.received_at is None
        assert failed.attempted_at is not None
        assert 0 < await redis.ttl("market:quote:CN:600519") <= 15
        await service.get_quotes([failed.symbol])
        assert calls == 1
        failed.attempted_at -= timedelta(seconds=16)
        await service.cache.write(failed.symbol, failed.model_dump_json())
        await redis.delete("market:refresh:CN:600519")
        service._attempts.clear()
        recovered = (await service.get_quotes([failed.symbol])).quotes[0]
        assert recovered.error is None
        assert recovered.received_at is not None
        assert calls == 2


async def test_owner_lost_old_failure_cannot_replace_winner():
    entered, release = asyncio.Event(), asyncio.Event()

    async def old_handler(request):
        entered.set()
        await release.wait()
        return httpx.Response(503)

    redis = fakeredis.aioredis.FakeRedis()
    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(old_handler)) as old_client,
        httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=record().encode("gb18030"))
            )
        ) as new_client,
    ):
        old = QuoteService(old_client, redis, Settings())
        new = QuoteService(new_client, redis, Settings())
        task = asyncio.create_task(old.get_quotes(["CN:600519"]))
        await entered.wait()
        assert 0 < await redis.ttl("market:refresh:CN:600519") <= 15
        old_owner = await redis.get("market:refresh:CN:600519")
        await redis.delete("market:refresh:CN:600519")
        winner = (await new.get_quotes(["CN:600519"])).quotes[0]
        assert await redis.get("market:refresh:CN:600519") != old_owner
        release.set()
        result = (await task).quotes[0]
        assert result.price == winner.price
        assert result.error is None
        assert old._local[winner.symbol].error is None
        assert (await old._read(winner.symbol)).received_at == winner.received_at


async def test_global_budget_shared_across_services():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=b"")

    redis = fakeredis.aioredis.FakeRedis()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        services = [QuoteService(client, redis, Settings()) for _ in range(2)]
        for index in range(31):
            result = await services[index % 2].get_quotes([f"US:TEST{index}"])
        assert calls == 30
        assert result.quotes[0].error.code == "UPSTREAM_BUDGET_EXCEEDED"


async def test_local_budget_when_redis_unavailable(monkeypatch):
    from cross_market.modules.market_data.application import service as service_module

    monkeypatch.setattr(service_module, "_local_budget_window", -1)
    monkeypatch.setattr(service_module, "_local_budget_count", 0)
    redis = SimpleNamespace(
        get=AsyncMock(side_effect=ConnectionError),
        set=AsyncMock(side_effect=ConnectionError),
    )
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=b"")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        services = [QuoteService(client, redis, Settings()) for _ in range(2)]
        for index in range(11):
            result = await services[index % 2].get_quotes([f"US:TEST{index}"])
        assert calls == 10
        assert result.quotes[0].error.code == "UPSTREAM_BUDGET_EXCEEDED"


async def test_success_cache_refreshes_after_configured_interval():
    redis = fakeredis.aioredis.FakeRedis()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=record().encode("gb18030"))
        )
    ) as client:
        service = QuoteService(client, redis, Settings())
        old = QuoteService.empty("CN:600519", "TEST", "测试")
        old.price = "10"
        old.received_at = datetime.now(UTC) - timedelta(seconds=31)
        old.error = None
        await service.cache.write(old.symbol, old.model_dump_json())
        result = (await service.get_quotes([old.symbol])).quotes[0]
        assert result.price == "12.345"
        assert result.received_at > old.received_at


async def test_warm_reads_do_not_wait_for_blocked_provider():
    entered, release = asyncio.Event(), asyncio.Event()

    async def handler(request):
        entered.set()
        await release.wait()
        return httpx.Response(200, content=b"")

    redis = fakeredis.aioredis.FakeRedis()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = QuoteService(client, redis, Settings())
        warm = QuoteService.empty("HK:00700", "TEST", "测试")
        warm.price = "10"
        warm.received_at = datetime.now(UTC)
        warm.error = None
        await service.cache.write(warm.symbol, warm.model_dump_json())
        blocked = asyncio.create_task(service.get_quotes(["US:AAPL"]))
        await entered.wait()
        try:
            result = await asyncio.wait_for(service.get_quotes([warm.symbol]), timeout=0.2)
            assert result.quotes[0].price == "10"
            cold = await asyncio.wait_for(service.get_quotes(["US:MSFT"]), timeout=0.2)
            assert cold.quotes[0].error.code == "REFRESH_THROTTLED"
        finally:
            release.set()
            await blocked


async def test_refresh_failure_preserves_latest_cache_after_lease_acquired():
    redis = fakeredis.aioredis.FakeRedis()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(503))
    ) as client:
        service = QuoteService(client, redis, Settings())
        stale = service.empty("CN:600519", "TEST", "测试")
        stale.price = "10"
        stale.received_at = datetime.now(UTC) - timedelta(seconds=60)
        stale.error = None
        latest = stale.model_copy(update={"price": "20", "received_at": datetime.now(UTC)})
        await service.cache.write(stale.symbol, stale.model_dump_json())
        acquire = service.cache.acquire

        async def updated_before_acquire(symbol):
            # 模拟初读后，另一进程发布新值并结束租约。
            await service.cache.write(symbol, latest.model_dump_json())
            return await acquire(symbol)

        service.cache.acquire = updated_before_acquire
        result = (await service.get_quotes([stale.symbol], refresh=True)).quotes[0]
        assert result.price == latest.price
        assert result.received_at == latest.received_at
        assert result.error.code == "PROVIDER_HTTP_ERROR"
        cached = await service._read(stale.symbol)
        assert cached.price == latest.price
        assert cached.received_at == latest.received_at


async def test_worker_lost_instance_lock_cannot_publish_even_with_symbol_lease():
    entered, release = asyncio.Event(), asyncio.Event()

    async def handler(request):
        entered.set()
        await release.wait()
        return httpx.Response(200, content=record(price="20").encode("gb18030"))

    redis = fakeredis.aioredis.FakeRedis()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = QuoteService(client, redis, Settings())
        old = service.empty("CN:600519", "TEST", "测试")
        old.price = "10"
        old.received_at = datetime.now(UTC)
        old.error = None
        await service.cache.write(old.symbol, old.model_dump_json())
        await redis.set("worker:test-owner", "owner-before")
        task = asyncio.create_task(service.get_quotes(
            [old.symbol], refresh=True,
            publication_guard=("worker:test-owner", "owner-before"),
        ))
        await entered.wait()
        try:
            assert await redis.get(f"market:refresh:{old.symbol}")
            await redis.set("worker:test-owner", "owner-after")
        finally:
            release.set()
        result = (await task).quotes[0]
        assert result.price == old.price
        assert result.received_at == old.received_at
        assert (await service._read(old.symbol)).price == old.price
        assert service._local[old.symbol].price == old.price
