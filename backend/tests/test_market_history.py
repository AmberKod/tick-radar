import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest

from cross_market.apps.api.main import create_app
from cross_market.modules.market_data.application.history import HistoryService
from cross_market.modules.market_data.infrastructure.tencent_history import (
    HistorySourceFailure,
    TencentHistorySource,
)
from cross_market.shared.config import Settings
from cross_market.shared.exceptions import AppError

ROW = ["2026-11-20", "10.00", "11.00", "12.00", "9.00", "00123.4500"]


@pytest.fixture(autouse=True)
def fixed_history_time(monkeypatch):
    class Clock(datetime):
        current = datetime(2026, 11, 22, 12, tzinfo=UTC)

        @classmethod
        def now(cls, tz=None):
            return cls.current.astimezone(tz)

    monkeypatch.setattr("cross_market.modules.market_data.application.history.datetime", Clock)
    return Clock


def payload(provider="sh600519", field="day", rows=None, jsonp=False, **changes):
    document = {"code": 0, "data": {provider: {field: [ROW] if rows is None else rows}}}
    document.update(changes)
    text = json.dumps(document, ensure_ascii=False)
    return (f"kline_day_{provider}={text};" if jsonp else text).encode()


def identity_payload(provider="usAAPL", actual="AAPL.OQ"):
    return payload(provider, data={provider: {"qt": {provider: ["", "", actual]}}})


@pytest.mark.parametrize(
    "symbol,provider,currency",
    [
        ("CN:600519", "sh600519", "CNY"),
        ("CN:000001", "sz000001", "CNY"),
        ("CN:920001", "bj920001", "CNY"),
        ("HK:00700", "hk00700", "HKD"),
        ("US:AAPL", "usAAPL", "USD"),
    ],
)
@pytest.mark.parametrize("adjustment,field", [("raw", "day"), ("qfq", "qfqday"), ("hfq", "hfqday")])
async def test_markets_adjustments_and_weekend(symbol, provider, currency, adjustment, field):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.host == "web.ifzq.gtimg.cn"
        assert "_var" not in request.url.params
        assert request.extensions["timeout"] == {
            "connect": 2, "read": 6, "write": 6, "pool": 6,
        }
        mode = "" if adjustment == "raw" else adjustment
        if symbol.startswith("US:") and len(calls) == 1:
            assert request.url.path == "/appstock/app/kline/kline"
            assert request.url.params["param"] == f"{provider},day,,2026-11-21,1,"
            return httpx.Response(200, content=identity_payload())
        actual = provider + ".OQ" if symbol.startswith("US:") else provider
        route = "fqkline/get"
        if not symbol.startswith("CN:"):
            route = "kline/kline" if adjustment == "raw" else (
                "usfqkline/get" if symbol.startswith("US:") else "hkfqkline/get"
            )
        assert request.url.path == f"/appstock/app/{route}"
        assert request.url.params["param"] == f"{actual},day,,2026-11-21,120,{mode}"
        return httpx.Response(200, content=payload(actual, field))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False) as client:
        service = HistoryService(client, Settings())
        if symbol.startswith("US:") and adjustment == "hfq":
            with pytest.raises(AppError) as failure:
                await service.get_history(symbol, adjustment=adjustment)
            assert failure.value.status == 422
            assert failure.value.code == "ADJUSTMENT_UNSUPPORTED"
            assert calls == []
            return
        result = await service.get_history(symbol, adjustment=adjustment)
    assert len(calls) == (2 if symbol.startswith("US:") else 1)
    assert result.currency == currency
    assert result.source == "tencent_history_public"
    assert result.period == "day"
    assert result.market == symbol.partition(":")[0]
    assert result.data_as_of == result.latest_date == date(2026, 11, 20)
    assert result.earliest_date == result.latest_date
    assert result.bars[0].volume == "00123.4500"
    assert result.bars[0].open == "10.00"
    assert result.actual_count == 1
    assert result.requested_limit == 120
    assert not result.history_complete
    assert result.observation_only
    assert any("非实时" in warning for warning in result.warnings)
    assert any("存储许可" in warning for warning in result.warnings)
    assert any(adjustment in warning for warning in result.warnings)


@pytest.mark.parametrize(
    "row",
    [
        ROW[:5],
        [*ROW, *(["extra"] * 27)],
        ["20261120", *ROW[1:]],
        ["2026-02-30", *ROW[1:]],
        [ROW[0], "NaN", *ROW[2:]],
        [ROW[0], "Infinity", *ROW[2:]],
        [ROW[0], "-1", *ROW[2:]],
        [ROW[0], "0", *ROW[2:]],
        [ROW[0], "1" * 65, *ROW[2:]],
        [ROW[0], 10, *ROW[2:]],
        [*ROW[:3], "10", *ROW[4:]],
        [*ROW[:4], "11", ROW[5]],
        [*ROW[:5], "-1"],
        [*ROW[:5], "NaN"],
        [*ROW[:5], "Infinity"],
        [*ROW[:5], "1" * 65],
    ],
)
async def test_invalid_bars_fail_entire_response(row):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=payload(rows=[row]))
        )
    ) as client:
        with pytest.raises(AppError) as failure:
            await HistoryService(client, Settings()).get_history("CN:600519")
    assert failure.value.code == "HISTORY_UNAVAILABLE"
    assert failure.value.status == 503
    assert isinstance(failure.value.__cause__, HistorySourceFailure)


@pytest.mark.parametrize("rows", [[ROW, ROW], [ROW, ["2026-11-19", *ROW[1:]]]])
async def test_duplicate_and_descending_dates(rows):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=payload(rows=rows))
        )
    ) as client:
        with pytest.raises(AppError):
            await HistoryService(client, Settings()).get_history("CN:600519")


@pytest.mark.parametrize(
    "body",
    [
        b"not jsonp",
        b"kline_day_sh600519=not json;",
        b"kline_day_sh600519=[];",
        payload(code=1),
        payload(code=False),
        payload(provider="hk00700"),
        payload(field="qfqday"),
        payload(rows={}),
        b'kline_day_sh600519={"code":0,"data":null};',
        b"x" * (2 * 1024 * 1024 + 1),
    ],
)
async def test_invalid_source_envelopes_and_size(body):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body))
    ) as client:
        with pytest.raises(AppError) as failure:
            await HistoryService(client, Settings()).get_history("CN:600519")
    assert failure.value.code == "HISTORY_UNAVAILABLE"


@pytest.mark.parametrize("adjustment", ["qfq", "hfq"])
async def test_missing_adjusted_series_never_falls_back_to_raw(adjustment):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=payload()))
    ) as client:
        with pytest.raises(AppError):
            await HistoryService(client, Settings()).get_history("CN:600519", adjustment=adjustment)


@pytest.mark.parametrize("status", [301, 302, 429, 500])
async def test_http_failure_without_redirects(status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, headers={"location": "https://qt.gtimg.cn/"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=True
    ) as client:
        with pytest.raises(AppError):
            await HistoryService(client, Settings()).get_history("CN:600519")
    assert len(calls) == 1


@pytest.mark.parametrize("error", [httpx.ConnectError("private"), httpx.ReadTimeout("private")])
async def test_transport_failures_are_stable(error):
    def handler(request):
        raise error

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        app = create_app(Settings())
        app.state.history_service = HistoryService(client, Settings())
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as api:
            response = await api.get("/api/v1/market/history", params={"symbol": "CN:600519"})
    assert response.status_code == 503
    assert response.json()["code"] == "HISTORY_UNAVAILABLE"
    assert "private" not in response.text


async def test_cache_key_expiry_and_copy_isolation(monkeypatch):
    calls = []
    clock = [100.0]
    monkeypatch.setattr(
        "cross_market.modules.market_data.application.history.monotonic", lambda: clock[0]
    )

    def handler(request):
        calls.append(request)
        provider, _, _, _, _, mode = request.url.params["param"].split(",")
        return httpx.Response(200, content=payload(provider, f"{mode}day"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = HistoryService(client, Settings())
        first = await service.get_history("CN:600519")
        first.bars.clear()
        assert (await service.get_history("CN:600519")).actual_count == 1
        assert len((await service.get_history("CN:600519")).bars) == 1
        assert len(calls) == 1
        await service.get_history("HK:00700")
        await service.get_history("CN:600519", adjustment="qfq")
        await service.get_history("CN:600519", limit=1)
        assert len(calls) == 4
        clock[0] += 60
        await service.get_history("CN:600519")
        assert len(calls) == 5


async def test_api_anonymous_defaults_validation_and_no_quote_or_calendar():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=payload()))
    ) as client:
        app = create_app(Settings())
        app.state.history_service = HistoryService(client, Settings())
        app.state.quote_service = AsyncMock()
        app.state.market_calendar = AsyncMock()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as api:
            response = await api.get("/api/v1/market/history", params={"symbol": "CN:600519"})
            assert response.status_code == 200
            assert response.json()["requested_limit"] == 120
            assert response.json()["adjustment"] == "raw"
            for query in [
                {"limit": 0},
                {"limit": 641},
                {"limit": -1},
                {"adjustment": "unknown"},
                {"symbol": "bad"},
            ]:
                response = await api.get(
                    "/api/v1/market/history", params={"symbol": "CN:600519", **query}
                )
                assert response.status_code == 422
                assert response.json()["code"] == "INVALID_HISTORY_REQUEST"
        assert app.state.quote_service.mock_calls == []
        assert app.state.market_calendar.mock_calls == []


@pytest.mark.parametrize("limit", [float("nan"), float("inf"), 1.5, True, 0, 641])
async def test_service_rejects_invalid_limit_without_network(limit):
    def handler(request):
        pytest.fail("无效请求不应触发网络")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError):
            await HistoryService(client, Settings()).get_history("CN:600519", limit)


@pytest.mark.parametrize("count,limit,complete", [(0, 120, False), (1, 1, True), (640, 640, True)])
async def test_coverage_empty_zero_volume_and_upper_bound(count, limit, complete):
    rows = []
    for ordinal in range(date(2024, 1, 1).toordinal(), date(2024, 1, 1).toordinal() + count):
        rows.append([date.fromordinal(ordinal).isoformat(), *ROW[1:5], "0"])
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=payload(rows=rows))
        )
    ) as client:
        result = await HistoryService(client, Settings()).get_history("CN:600519", limit)
    assert result.history_complete is complete
    assert result.actual_count == count
    assert result.data_as_of == (date.fromisoformat(rows[-1][0]) if count else None)


async def test_vendor_cannot_exceed_requested_limit():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, content=payload(rows=[["2026-11-19", *ROW[1:]], ROW])
            )
        )
    ) as client:
        with pytest.raises(AppError):
            await HistoryService(client, Settings()).get_history("CN:600519", limit=1)


async def test_gb18030_body():
    body = payload(message="历史日线").decode("utf-8").encode("gb18030")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body))
    ) as client:
        assert (await HistoryService(client, Settings()).get_history("CN:600519")).actual_count == 1


@pytest.mark.parametrize("jsonp", [False, True])
@pytest.mark.parametrize("extra_count", [0, 1, 26])
async def test_hk_extra_fields_and_metadata(jsonp, extra_count):
    body = payload(
        "hk00700", "qfqday", rows=[[*ROW, *([{"action": "dividend"}] * extra_count)]],
        jsonp=jsonp,
        data={"hk00700": {
            "qfqday": [[*ROW, *([{"action": "dividend"}] * extra_count)]],
            "qt": {"hk00700": {"name": "腾讯控股"}},
        }},
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body))
    ) as client:
        result = await HistoryService(client, Settings()).get_history("HK:00700", adjustment="qfq")
    assert result.bars[0].volume == ROW[5]
    assert result.bars[0].open == ROW[1]


@pytest.mark.parametrize("adjustment,field", [("raw", "qfqday"), ("raw", "hfqday")])
async def test_raw_never_uses_adjusted_series(adjustment, field):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=payload(field=field))
        )
    ) as client:
        with pytest.raises(AppError):
            await HistoryService(client, Settings()).get_history("CN:600519", adjustment=adjustment)


@pytest.mark.parametrize("ticker,suffix", [("AAPL", ".OQ"), ("BRK.B", ".N"),
                                          ("BRK.A", ".A"), ("SPY", ".AM")])
@pytest.mark.parametrize("adjustment", ["raw", "qfq"])
async def test_us_strict_identity_preserves_class_ticker(ticker, suffix, adjustment):
    calls = []
    provider = "us" + ticker
    qualified = provider + suffix

    def handler(request):
        calls.append(request)
        assert request.url.host == "web.ifzq.gtimg.cn"
        if len(calls) == 1:
            assert request.url.params["param"].startswith(provider + ",day,")
            return httpx.Response(200, content=identity_payload(provider, ticker + suffix))
        assert request.url.params["param"].startswith(qualified + ",day,")
        field = "day" if adjustment == "raw" else "qfqday"
        return httpx.Response(200, content=payload(qualified, field))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await HistoryService(client, Settings()).get_history(
            "US:" + ticker, adjustment=adjustment
        )
    assert result.symbol == "US:" + ticker
    assert len(calls) == 2


@pytest.mark.parametrize("actual", ["AAPL", "AAPL.O", "AAPL.OQ.evil", "MSFT.OQ", "aapl.OQ", None])
async def test_us_wrong_identity_stops_before_history(actual):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=identity_payload(actual=actual))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AppError) as failure:
            await HistoryService(client, Settings()).get_history("US:AAPL")
    assert failure.value.code == "HISTORY_UNAVAILABLE"
    assert len(calls) == 1


@pytest.mark.parametrize("body", [payload("usMSFT"), payload("usAAPL", data={}),
                                  payload("usAAPL", data={"usAAPL": {"qt": {}}})])
async def test_us_invalid_identity_root_stops_before_history(body):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AppError):
            await HistoryService(client, Settings()).get_history("US:AAPL")
    assert len(calls) == 1


@pytest.mark.parametrize("symbol,provider,end", [
    ("CN:600519", "sh600519", "2026-11-22"),
    ("HK:00700", "hk00700", "2026-11-22"),
    ("US:AAPL", "usAAPL.OQ", "2026-11-21"),
])
@pytest.mark.parametrize("offset", [1, 2])
async def test_market_local_today_and_future_fail_closed(
    symbol, provider, end, offset, fixed_history_time
):
    fixed_history_time.current = datetime(2026, 11, 23, 1, tzinfo=UTC)
    invalid_day = date.fromisoformat(end) + timedelta(days=offset)

    def handler(request):
        assert request.url.params["param"].split(",")[3] == end
        if request.url.params["param"].startswith("usAAPL,"):
            return httpx.Response(200, content=identity_payload())
        return httpx.Response(200, content=payload(provider, rows=[
            ROW, [invalid_day.isoformat(), *ROW[1:]],
        ]))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = HistoryService(client, Settings())
        with pytest.raises(AppError) as failure:
            await service.get_history(symbol)
        assert service._cache == {}
    assert failure.value.code == "HISTORY_UNAVAILABLE"


async def test_cache_end_changes_at_new_york_midnight(fixed_history_time):
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.params["param"].startswith("usAAPL,"):
            return httpx.Response(200, content=identity_payload())
        return httpx.Response(200, content=payload("usAAPL.OQ"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = HistoryService(client, Settings())
        fixed_history_time.current = datetime(2026, 11, 23, 4, 59, tzinfo=UTC)
        await service.get_history("US:AAPL")
        fixed_history_time.current = datetime(2026, 11, 23, 5, 0, tzinfo=UTC)
        await service.get_history("US:AAPL")
    assert [request.url.params["param"].split(",")[3] for request in calls] == [
        "2026-11-21", "2026-11-21", "2026-11-22",
    ]


async def test_cached_checked_at_is_not_refreshed(fixed_history_time):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=payload()))
    ) as client:
        service = HistoryService(client, Settings())
        first = await service.get_history("CN:600519")
        fixed_history_time.current += timedelta(seconds=30)
        second = await service.get_history("CN:600519")
    assert second.checked_at == first.checked_at
    assert second.checked_at < fixed_history_time.current


async def test_concurrent_same_key_fetches_once():
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def handler(request):
        calls.append(request)
        entered.set()
        await release.wait()
        return httpx.Response(200, content=payload())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = HistoryService(client, Settings())
        first = asyncio.create_task(service.get_history("CN:600519"))
        await entered.wait()
        second = asyncio.create_task(service.get_history("CN:600519"))
        release.set()
        results = await asyncio.gather(first, second)
    assert len(calls) == 1
    assert results[0] == results[1]
    assert results[0] is not results[1]
    assert results[0].bars is not results[1].bars


async def test_exception_releases_lock_and_does_not_cache():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(500) if len(calls) == 1 else httpx.Response(200, content=payload())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = HistoryService(client, Settings())
        with pytest.raises(AppError):
            await service.get_history("CN:600519")
        assert not service._lock.locked()
        assert service._cache == {}
        assert (await service.get_history("CN:600519")).actual_count == 1
    assert len(calls) == 2


async def test_lock_wait_timeout_does_not_release_other_owner():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: pytest.fail("等待锁时不应请求上游"))
    ) as client:
        service = HistoryService(client, Settings())
        await service._lock.acquire()
        try:
            with pytest.raises(AppError) as failure:
                await service.get_history("CN:600519")
            assert failure.value.code == "HISTORY_BUSY"
            assert failure.value.status == 503
            assert service._lock.locked()
        finally:
            service._lock.release()


async def test_cancelled_fetch_releases_lock_for_next_request():
    entered = asyncio.Event()
    calls = []

    async def handler(request):
        calls.append(request)
        if len(calls) == 1:
            entered.set()
            await asyncio.Event().wait()
        return httpx.Response(200, content=payload())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = HistoryService(client, Settings())
        pending = asyncio.create_task(service.get_history("CN:600519"))
        await entered.wait()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert not service._lock.locked()
        assert service._cache == {}
        assert (await service.get_history("CN:600519")).actual_count == 1
    assert len(calls) == 2


async def test_us_api_identity_never_uses_quote_or_calendar():
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.host == "web.ifzq.gtimg.cn"
        body = identity_payload() if len(calls) == 1 else payload("usAAPL.OQ")
        return httpx.Response(200, content=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        app = create_app(Settings())
        app.state.history_service = HistoryService(client, Settings())
        app.state.quote_service = AsyncMock()
        app.state.market_calendar = AsyncMock()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as api:
            response = await api.get("/api/v1/market/history", params={"symbol": "US:AAPL"})
            assert response.status_code == 200
            response = await api.get("/api/v1/market/history", params={
                "symbol": "US:AAPL", "adjustment": "hfq",
            })
            assert response.status_code == 422
            assert response.json()["code"] == "ADJUSTMENT_UNSUPPORTED"
        assert app.state.quote_service.mock_calls == []
        assert app.state.market_calendar.mock_calls == []
    assert len(calls) == 2


async def test_history_cache_is_bounded_to_32(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(
        "cross_market.modules.market_data.infrastructure.tencent_history.monotonic",
        lambda: clock[0],
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=payload()))
    ) as client:
        service = HistoryService(client, Settings())
        for limit in range(1, 35):
            clock[0] += 60
            await service.get_history("CN:600519", limit=limit)
            assert len(service._cache) <= 32
        assert len(service._cache) == 32
        assert {key[2] for key in service._cache} == set(range(3, 35))


async def test_source_budget_rejects_31st_http_and_resets(monkeypatch):
    clock = [120.0]
    monkeypatch.setattr(
        "cross_market.modules.market_data.infrastructure.tencent_history.monotonic",
        lambda: clock[0],
    )
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=payload())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = TencentHistorySource(client)
        for _ in range(30):
            await source.fetch("sh600519", "raw", 120, end=date(2026, 11, 21))
        with pytest.raises(HistorySourceFailure):
            await source.fetch("sh600519", "raw", 120, end=date(2026, 11, 21))
        assert len(calls) == 30
        clock[0] += 60
        await source.fetch("sh600519", "raw", 120, end=date(2026, 11, 21))
    assert len(calls) == 31


async def test_identity_requests_share_http_budget(monkeypatch):
    monkeypatch.setattr(
        "cross_market.modules.market_data.infrastructure.tencent_history.monotonic", lambda: 120.0
    )
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.params["param"].startswith("usAAPL,"):
            return httpx.Response(200, content=identity_payload())
        return httpx.Response(200, content=payload())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = TencentHistorySource(client)
        for _ in range(29):
            await source.fetch("sh600519", "raw", 120, end=date(2026, 11, 21))
        with pytest.raises(HistorySourceFailure):
            await source.fetch("usAAPL", "raw", 120, end=date(2026, 11, 21))
    assert len(calls) == 30
    assert calls[-1].url.params["param"].startswith("usAAPL,")


async def test_identity_cache_ttl_and_bound(monkeypatch):
    clock = [120.0]
    monkeypatch.setattr(
        "cross_market.modules.market_data.infrastructure.tencent_history.monotonic",
        lambda: clock[0],
    )
    calls = []

    def handler(request):
        calls.append(request)
        provider = request.url.params["param"].split(",")[0]
        return httpx.Response(200, content=identity_payload(provider, provider[2:] + ".OQ"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = TencentHistorySource(client)
        end = date(2026, 11, 21)
        assert await source._us_identity("usAAPL", end) == "usAAPL.OQ"
        clock[0] += 299
        await source._us_identity("usAAPL", end)
        assert len(calls) == 1
        clock[0] += 1
        await source._us_identity("usAAPL", end)
        assert len(calls) == 2
        for index in range(65):
            clock[0] += 60
            await source._us_identity(f"usT{index}", end)
            assert len(source._identities) <= 64
        assert len(source._identities) == 64
        assert "usAAPL" not in source._identities
        assert "usT0" not in source._identities
