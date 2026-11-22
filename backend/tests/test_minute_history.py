import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI

from cross_market.modules.market_data.application.minute import MinuteHistoryService
from cross_market.modules.market_data.infrastructure.tencent_minute import (
    MinuteSourceFailure,
    TencentMinuteSource,
    parse_bars,
)
from cross_market.modules.market_data.interfaces.router import router
from cross_market.shared.config import Settings
from cross_market.shared.exceptions import AppError, register_exception_handlers

ROW = ["202611200945", "10.00", "11.00", "12.00", "9.00", "00123.4500", {}]


def payload(rows=None, provider="sh600519", **changes):
    doc = {"code": 0, "data": {provider: {"m15": [ROW] if rows is None else rows}}}
    doc.update(changes)
    return json.dumps(doc).encode()


@pytest.fixture
def clock(monkeypatch):
    class Clock(datetime):
        current = datetime(2026, 11, 20, 2, tzinfo=UTC)

        @classmethod
        def now(cls, tz=None):
            return cls.current.astimezone(tz)

    monkeypatch.setattr("cross_market.modules.market_data.application.minute.datetime", Clock)
    return Clock


@pytest.mark.parametrize("symbol,provider", [("CN:600519", "sh600519"), ("CN:000001", "sz000001")])
async def test_source_contract_metadata_cache_and_copy(symbol, provider, clock):
    calls = []

    def handler(request):
        calls.append(request)
        assert str(request.url).startswith("https://ifzq.gtimg.cn/appstock/app/kline/mkline?")
        assert request.url.params["param"] == f"{provider},m15,,320"
        assert request.extensions["timeout"]["connect"] == 2
        return httpx.Response(200, content=payload(provider=provider))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False) as client:
        service = MinuteHistoryService(client, Settings())
        first = await service.get_history(symbol, 1)
        assert first.bars[0].timestamp == datetime(2026, 11, 20, 1, 45, tzinfo=UTC)
        assert first.bars[0].source_time_raw == ROW[0]
        assert first.bars[0].volume == "00123.4500"
        assert first.adjustment == "vendor_unverified"
        assert first.timestamp_semantics == "VENDOR_BAR_LABEL_UNVERIFIED"
        first.bars[0].close = "999"
        second = await service.get_history(symbol, 2)
        assert second.bars[0].close == "11.00"
        assert second.checked_at == first.checked_at
        assert second.requested_limit == 2 and not second.history_complete
        assert len(calls) == 1


async def test_recent_future_filter_reapplied_to_cache(clock):
    rows = [ROW, ["202611201000", *ROW[1:]], ["202611201015", *ROW[1:]]]
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, content=payload(rows))
    )) as client:
        service = MinuteHistoryService(client, Settings())
        first = await service.get_history("CN:600519")
        assert first.actual_count == 1
        assert any("排除2根" in warning for warning in first.warnings)
        clock.current += timedelta(minutes=15)
        second = await service.get_history("CN:600519")
        assert second.actual_count == 2 and second.checked_at == first.checked_at


@pytest.mark.parametrize("symbol", ["HK:00700", "US:AAPL", "CN:920001", "CN:830001"])
async def test_unsupported_without_network(symbol):
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda _: pytest.fail("不支持的市场不得访问网络")
    )) as client:
        with pytest.raises(AppError) as failure:
            await MinuteHistoryService(client, Settings()).get_history(symbol)
        assert failure.value.code == "MINUTE_MARKET_UNSUPPORTED"


@pytest.mark.parametrize("clock_label", ["0945", "1130", "1315", "1500"])
def test_session_boundaries(clock_label):
    assert parse_bars(payload([[f"20261120{clock_label}", *ROW[1:]]]), "sh600519")


@pytest.mark.parametrize("raw", [
    "202611200930", "202611201145", "202611201300", "202611201515", "202611200946",
    "202613200945", "20261120094500", "20261120094x",
])
def test_invalid_timestamp(raw):
    with pytest.raises(MinuteSourceFailure):
        parse_bars(payload([[raw, *ROW[1:]]]), "sh600519")


@pytest.mark.parametrize("index,value", [(1, "0"), (2, "NaN"), (3, "10"), (4, "12"),
                                        (5, "-1"), (1, "1" * 65), (1, 10)])
def test_invalid_ohlcv(index, value):
    row = ROW.copy()
    row[index] = value
    with pytest.raises(MinuteSourceFailure):
        parse_bars(payload([row]), "sh600519")


def test_order_shape_identity_and_empty():
    assert parse_bars(payload([]), "sh600519") == []
    for body in [payload([ROW, ROW]), payload([ROW[:5]]), payload([ROW + [None] * 26]),
                 payload([ROW] * 321), payload(provider="sz000001"), payload(code=True),
                 b'{"code":0,"data":{"sh600519":{}}}', b"not json"]:
        with pytest.raises(MinuteSourceFailure):
            parse_bars(body, "sh600519")
    # 周末源记录保留，不借日历误吞数据。
    assert parse_bars(payload([["202611210945", *ROW[1:]]]), "sh600519")


@pytest.mark.parametrize("status,body", [(302, b""), (500, b""), (200, b"x" * (2097153))])
async def test_network_status_body_limit(status, body):
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda _: httpx.Response(status, content=body)
    )) as client:
        with pytest.raises(AppError) as failure:
            await MinuteHistoryService(client, Settings()).get_history("CN:600519")
        assert failure.value.code == "MINUTE_HISTORY_UNAVAILABLE"


async def test_budget_and_transport_error(monkeypatch):
    monkeypatch.setattr("cross_market.modules.market_data.infrastructure.tencent_minute.monotonic",
                        lambda: 100)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=payload([]))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = TencentMinuteSource(client)
        for _ in range(30):
            await source.fetch("sh600519")
        with pytest.raises(MinuteSourceFailure):
            await source.fetch("sh600519")
        assert len(calls) == 30
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: (_ for _ in ()).throw(httpx.ConnectError("离线", request=request))
    )) as client:
        with pytest.raises(MinuteSourceFailure):
            await TencentMinuteSource(client).fetch("sh600519")


async def test_cancel_releases_lock_and_cache_bounded():
    entered, release = asyncio.Event(), asyncio.Event()
    async with httpx.AsyncClient() as client:
        service = MinuteHistoryService(client, Settings())

        async def fetch(provider):
            entered.set()
            await release.wait()
            return []

        service.source.fetch = fetch
        pending = asyncio.create_task(service.get_history("CN:600519"))
        await entered.wait()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert not service._lock.locked()
        release.set()
        for number in range(33):
            await service.get_history(f"CN:{600000 + number}")
        assert len(service._cache) == 32


async def test_cache_expiry_and_busy(monkeypatch):
    tick = [0]
    monkeypatch.setattr("cross_market.modules.market_data.application.minute.monotonic",
                        lambda: tick[0])
    calls = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: calls.append(request) or httpx.Response(200, content=payload([]))
    )) as client:
        service = MinuteHistoryService(client, Settings())
        await service.get_history("CN:600519")
        tick[0] = 61
        await service.get_history("CN:600519")
        assert len(calls) == 2
        await service._lock.acquire()
        try:
            with pytest.raises(AppError) as failure:
                await service.get_history("CN:000001")
            assert failure.value.code == "MINUTE_HISTORY_BUSY"
        finally:
            service._lock.release()


async def test_route_parameters():
    app = FastAPI()
    app.include_router(router)
    register_exception_handlers(app)
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, content=payload([]))
    )) as source_client:
        app.state.minute_history_service = MinuteHistoryService(source_client, Settings())
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as c:
            for query in ["limit=0", "limit=321", "limit=true", "limit=1.5", "adjustment=raw"]:
                response = await c.get(f"/api/v1/market/history/minute?symbol=CN:600519&{query}")
                assert response.status_code == 422
            response = await c.get("/api/v1/market/history/minute?symbol=CN:600519&limit=1")
            assert response.status_code == 200 and response.json()["bars"] == []
            response = await c.get("/api/v1/market/history/minute?symbol=HK:00700")
            assert response.status_code == 422
            assert response.json()["code"] == "MINUTE_MARKET_UNSUPPORTED"
