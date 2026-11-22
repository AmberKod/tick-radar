from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from cross_market.modules.indicators.application.minute import MinuteIndicatorService
from cross_market.modules.indicators.application.minute_schemas import MinuteIndicatorRequest
from cross_market.modules.indicators.domain.calculations import (
    Bar,
    Params,
    calculate_daily,
    calculate_intraday,
)
from cross_market.modules.indicators.interfaces.router import router
from cross_market.modules.market_data.application.minute_schemas import (
    MinuteBar,
    MinuteHistoryResponse,
)


def history(count):
    start = datetime(2026, 11, 1, tzinfo=UTC)
    bars = [MinuteBar(
        timestamp=start + timedelta(minutes=15 * index), source_time_raw="202611010945",
        open="10", high="12", low="9", close="11", volume="123",
    ) for index in range(count)]
    return MinuteHistoryResponse(
        symbol="CN:600519", bars=bars, requested_limit=count, actual_count=count,
        earliest_timestamp=bars[0].timestamp if bars else None,
        latest_timestamp=bars[-1].timestamp if bars else None,
        data_as_of=bars[-1].timestamp if bars else None,
        checked_at=datetime.now(UTC), history_complete=True, coverage_reason="测试",
        warnings=["vendor_unverified"],
    )


def test_formula_equivalence_and_same_day_timestamps():
    daily, intraday = [], []
    for index in range(40):
        close = Decimal(10 + index % 7)
        prices = (close + 2, close - 2, close)
        daily.append(Bar(date(2026, 1, 1) + timedelta(days=index), *prices))
        intraday.append(Bar(datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=15 * index),
                            *prices))
    expected = calculate_daily(daily)
    actual = calculate_intraday(intraday)
    assert len({point.date for point in actual}) == 40
    for left, right in zip(expected, actual, strict=True):
        assert {k: v for k, v in asdict(left).items() if k != "date"} == {
            k: v for k, v in asdict(right).items() if k != "date"
        }
    assert actual[0].ma is None and actual[-1].ma is not None
    assert calculate_intraday(intraday[:20]) == actual[:20]


def test_key_validation():
    prices = (Decimal(12), Decimal(9), Decimal(11))
    for key in [date(2026, 1, 1), datetime(2026, 1, 1)]:
        with pytest.raises(ValueError):
            calculate_intraday([Bar(key, *prices)])
    aware = Bar(datetime(2026, 1, 1, tzinfo=UTC), *prices)
    with pytest.raises(ValueError):
        calculate_intraday([aware, aware])
    with pytest.raises(ValueError):
        calculate_daily([aware])
    with pytest.raises(ValueError):
        calculate_intraday([aware, Bar(aware.day - timedelta(minutes=15), *prices)])


@pytest.mark.parametrize("changes", [{"limit": True}, {"limit": 251}, {"limit": 0},
                                      {"limit": "2"}, {"bars": []}, {"adjustment": "raw"}])
def test_request_strict(changes):
    with pytest.raises(ValidationError):
        MinuteIndicatorRequest(symbol="CN:600519", **changes)


async def test_service_warmup_metadata_cap_and_nulls():
    reader = AsyncMock()
    reader.get_history.return_value = history(320)
    request = MinuteIndicatorRequest(symbol="CN:600519", limit=250)
    response = await MinuteIndicatorService(reader).calculate_minute(request)
    reader.get_history.assert_awaited_once_with("CN:600519", 320)
    assert response.algorithm_version == "m15-v1"
    assert response.source_bars == 320 and response.warmup_bars == 70
    assert response.warmup_requested == 70 and response.visible_bars == 250
    assert response.history.actual_count == 250 and response.history.requested_limit == 250
    assert response.points[0].timestamp == response.history.bars[0].timestamp
    assert response.as_of == response.history.latest_timestamp
    assert response.history.adjustment == "vendor_unverified"
    assert len(response.parameter_hash) == 64
    reader.get_history.return_value = history(1)
    short = await MinuteIndicatorService(reader).calculate_minute(request)
    assert all(value is None for key, value in short.points[0].model_dump().items()
               if key != "timestamp")
    assert any("预热不足" in warning for warning in short.warnings)
    reader.get_history.return_value = history(0)
    empty = await MinuteIndicatorService(reader).calculate_minute(request)
    assert empty.points == [] and empty.as_of is None and empty.history.data_as_of is None


async def test_large_warmup_is_capped():
    reader = AsyncMock()
    reader.get_history.return_value = history(320)
    request = MinuteIndicatorRequest(symbol="CN:600519", limit=250,
                                      parameters={"ma_period": 120, "atr_period": 120})
    result = await MinuteIndicatorService(reader).calculate_minute(request)
    reader.get_history.assert_awaited_once_with("CN:600519", 320)
    assert result.warmup_requested == 600
    assert any("预热不足" in warning for warning in result.warnings)
    assert Params().ma_period == 10


async def test_public_minute_indicator_route():
    reader = AsyncMock()
    reader.get_history.return_value = history(1)
    app = FastAPI()
    app.include_router(router)
    app.state.minute_indicator_service = MinuteIndicatorService(reader)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/v1/indicators/minute", json={"symbol": "CN:600519"})
        assert response.status_code == 200
        assert response.json()["algorithm_version"] == "m15-v1"
        assert response.json()["points"][0]["timestamp"].endswith("Z")
        for extra in [{"bars": []}, {"adjustment": "raw"}, {"limit": True}]:
            response = await client.post("/api/v1/indicators/minute",
                                         json={"symbol": "CN:600519", **extra})
            assert response.status_code == 422
