import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pandas as pd
import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from cross_market.modules.indicators.application.schemas import (
    IndicatorParameters,
    IndicatorRequest,
)
from cross_market.modules.indicators.application.service import IndicatorService
from cross_market.modules.indicators.domain.calculations import Bar, Params, calculate_daily
from cross_market.modules.indicators.interfaces.router import router
from cross_market.modules.market_data.application.history_schemas import HistoryBar, HistoryResponse
from cross_market.shared.exceptions import AppError, register_exception_handlers

SMALL = Params(
    ma_period=3,
    macd_fast=2,
    macd_slow=3,
    macd_signal=2,
    kdj_lookback=3,
    kdj_k=2,
    kdj_d=2,
    atr_period=3,
)


def make_bars(values):
    return [
        Bar(date(2025, 1, 1) + timedelta(days=i), Decimal(str(v)), Decimal(str(v)), Decimal(str(v)))
        for i, v in enumerate(values)
    ]


def source_history(count=200):
    bars = [
        HistoryBar(
            date=date(2025, 1, 1) + timedelta(days=i),
            open=str(i + 10),
            high=str(i + 12),
            low=str(i + 9),
            close=str(i + 11),
            volume="00100.00",
        )
        for i in range(count)
    ]
    return HistoryResponse(
        symbol="US:AAPL",
        market="US",
        currency="USD",
        adjustment="qfq",
        bars=bars,
        requested_limit=count,
        actual_count=count,
        latest_date=bars[-1].date if bars else None,
        earliest_date=bars[0].date if bars else None,
        checked_at=datetime(2026, 1, 1, tzinfo=UTC),
        data_as_of=bars[-1].date if bars else None,
        warnings=["源提示"],
        history_complete=True,
        coverage_reason="源覆盖",
    )


def test_sma_ema_seed_and_nulls():
    points = calculate_daily(make_bars([1, 2, 4, 8, 16]), SMALL)
    assert points[1].ma is points[1].dif is points[1].dea is None
    assert points[2].ma == "2.3333333333"
    assert points[2].dif == "0.8333333333"
    assert points[2].dea is points[2].macd is None
    assert points[3].dif == "1.2222222222"
    assert points[3].dea == "1.0277777778"
    assert points[3].macd == "0.3888888889"
    assert points[4].ma == "9.3333333333"


@pytest.mark.parametrize("values,sign", [([10] * 30, 0), (range(1, 31), 1), (range(30, 0, -1), -1)])
def test_macd_flat_up_down(values, sign):
    point = calculate_daily(make_bars(values), SMALL)[-1]
    assert (Decimal(point.dif) > 0) - (Decimal(point.dif) < 0) == sign
    if sign == 0:
        assert point.macd == point.dea == point.dif == "0.0000000000"


def test_kdj_flat_monotonic_and_negative_j():
    flat = calculate_daily(make_bars([10] * 6), SMALL)
    assert flat[1].k is None
    assert flat[2].k == flat[2].d == flat[2].j == "50.0000000000"
    rising = calculate_daily(make_bars(range(1, 20)), SMALL)
    assert Decimal(rising[2].k) == 75
    falling = calculate_daily(make_bars([20, 19, 18, 17, 16]), SMALL)
    assert Decimal(falling[3].j) < 0


def test_atr_gap_seed_and_wilder():
    points = calculate_daily(make_bars([10, 12, 16, 22]), SMALL)
    assert points[1].atr is None
    assert points[2].atr == "2.0000000000"
    assert points[3].atr == "3.3333333333"
    bars = [replace(bar, high=bar.high + 2, low=bar.low - 1) for bar in make_bars([10, 11, 12])]
    assert calculate_daily(bars, SMALL)[2].atr == "3.0000000000"


def test_prefix_unchanged_and_decimal_context_independent():
    bars = make_bars([str(100 + i % 13) + ".123456789012345678901" for i in range(90)])
    expected = calculate_daily(bars, SMALL)
    assert calculate_daily(bars[:30], SMALL) == expected[:30]
    with localcontext() as context:
        context.prec = 6
        assert calculate_daily(bars, SMALL) == expected
    assert calculate_daily([], SMALL) == []


def test_independent_pandas_reference():
    bars = [
        replace(bar, high=bar.high + 2, low=bar.low - 1)
        for bar in make_bars([100 + (i * 7 % 19) for i in range(80)])
    ]
    closes = pd.Series([float(bar.close) for bar in bars])
    highs = pd.Series([float(bar.high) for bar in bars])
    lows = pd.Series([float(bar.low) for bar in bars])

    def seeded_ema(series, period):
        valid = series.dropna()
        seeded = valid.iloc[period - 1 :].copy()
        seeded.iloc[0] = valid.iloc[:period].mean()
        return seeded.ewm(span=period, adjust=False).mean().reindex(series.index)

    dif = seeded_ema(closes, 2) - seeded_ema(closes, 3)
    dea = seeded_ema(dif, 2)
    high, low = highs.rolling(3).max(), lows.rolling(3).min()
    rsv = (closes - low) / (high - low) * 100
    k = (
        pd.concat([pd.Series([50.0], index=[1]), rsv.dropna()])
        .ewm(alpha=0.5, adjust=False)
        .mean()
        .drop(index=1)
        .reindex(closes.index)
    )
    d = (
        pd.concat([pd.Series([50.0], index=[1]), k.dropna()])
        .ewm(alpha=0.5, adjust=False)
        .mean()
        .drop(index=1)
        .reindex(closes.index)
    )
    tr = pd.concat(
        [highs - lows, (highs - closes.shift()).abs(), (lows - closes.shift()).abs()], axis=1
    ).max(axis=1)
    atr = tr.iloc[2:].copy()
    atr.iloc[0] = tr.iloc[:3].mean()
    atr = atr.ewm(alpha=1 / 3, adjust=False).mean().reindex(closes.index)
    reference = {
        "ma": closes.rolling(3).mean(),
        "dif": dif,
        "dea": dea,
        "macd": 2 * (dif - dea),
        "k": k,
        "d": d,
        "j": 3 * k - 2 * d,
        "atr": atr,
    }
    for index, point in enumerate(calculate_daily(bars, SMALL)):
        for name, series in reference.items():
            actual, expected = getattr(point, name), series.iloc[index]
            if pd.isna(expected):
                assert actual is None
            else:
                assert float(actual) == pytest.approx(expected, abs=1e-9)


def test_rounding_half_even_and_negative_zero():
    bars = make_bars(["1.00000000005"] * 4)
    assert calculate_daily(bars, SMALL)[2].ma == "1.0000000000"
    tiny = calculate_daily(make_bars(["1.00000000001", "1", "1", "1"]), SMALL)
    assert tiny[-1].dif == "0.0000000000"


@pytest.mark.parametrize(
    "changes",
    [
        {"ma_period": True},
        {"ma_period": 1},
        {"macd_fast": 3, "macd_slow": 3},
        {"kdj_k": 61},
        {"atr_period": 121},
        {"macd_signal": "5"},
    ],
)
def test_bad_domain_parameters(changes):
    with pytest.raises(ValueError):
        Params(**changes)


@pytest.mark.parametrize(
    "kind", ["duplicate", "descending", "nan", "inf", "zero", "range", "float"]
)
def test_bad_bars(kind):
    bars = make_bars([10, 11])
    if kind == "duplicate":
        bars[1] = replace(bars[1], day=bars[0].day)
    elif kind == "descending":
        bars.reverse()
    else:
        bad = {
            "nan": Decimal("NaN"),
            "inf": Decimal("Infinity"),
            "zero": Decimal(0),
            "range": Decimal(20),
            "float": 10.0,
        }[kind]
        bars[0] = replace(bars[0], close=bad)
    with pytest.raises(ValueError):
        calculate_daily(bars)


@pytest.mark.parametrize(
    "changes",
    [
        {"limit": True},
        {"limit": "2"},
        {"limit": 1.0},
        {"limit": 501},
        {"limit": 0},
        {"bars": []},
        {"symbol": " "},
        {"symbol": "A" * 41},
        {"parameters": {"ma_period": 2.0}},
        {"parameters": {"extra": 1}},
        {"parameters": {"macd_fast": 13}},
        {"adjustment": "bad"},
    ],
)
def test_request_validation(changes):
    with pytest.raises(ValidationError):
        IndicatorRequest.model_validate({"symbol": "US:AAPL", **changes})


async def test_service_source_trimming_hash_and_no_mutation():
    source = source_history(200)
    original = source.model_dump()
    reader = SimpleNamespace(get_history=AsyncMock(return_value=source))
    request = IndicatorRequest(symbol="US:AAPL", limit=120, adjustment="qfq")
    response = await IndicatorService(reader).calculate_daily(request)
    reader.get_history.assert_awaited_once_with("US:AAPL", 190, "qfq")
    assert source.model_dump() == original
    assert response.history.checked_at == source.checked_at
    assert response.history.source == source.source
    assert response.history.adjustment == "qfq"
    assert response.history.requested_limit == 120
    assert response.history.actual_count == response.visible_bars == 120
    assert response.source_bars == 200
    assert response.warmup_bars == 80
    assert response.warmup_requested == 70
    assert [p.date for p in response.points] == [b.date for b in response.history.bars]
    assert response.history.earliest_date == source.bars[80].date
    assert response.as_of == response.history.data_as_of == source.bars[-1].date
    canonical = json.dumps(request.parameters.model_dump(), sort_keys=True, separators=(",", ":"))
    assert response.parameter_hash == hashlib.sha256(canonical.encode()).hexdigest()
    assert response.calculated_at.utcoffset() == timedelta(0)
    assert response.formula_notes and response.observation_only
    response.history.bars[0].close = "999"
    assert source.model_dump() == original


@pytest.mark.parametrize("count", [0, 2, 140])
async def test_service_insufficient_history_and_cap(count):
    source = source_history(count)
    source.history_complete = False
    reader = SimpleNamespace(get_history=AsyncMock(return_value=source))
    request = IndicatorRequest(
        symbol="US:AAPL",
        limit=500,
        parameters=IndicatorParameters(macd_slow=120, atr_period=120),
    )
    response = await IndicatorService(reader).calculate_daily(request)
    reader.get_history.assert_awaited_once_with("US:AAPL", 640, "raw")
    assert response.warmup_requested == 600
    assert response.warmup_bars == 0
    assert response.visible_bars == count
    assert not response.history.history_complete
    assert any("预热不足" in warning for warning in response.warnings)
    assert response.points == [] if count == 0 else response.points[0].ma is None


async def test_service_full_cap_and_custom_parameters():
    source = source_history(640)
    reader = SimpleNamespace(get_history=AsyncMock(return_value=source))
    parameters = IndicatorParameters(ma_period=2, macd_slow=120, atr_period=120)
    response = await IndicatorService(reader).calculate_daily(
        IndicatorRequest(
            symbol="US:AAPL",
            limit=500,
            adjustment="qfq",
            parameters=parameters,
        )
    )
    assert response.parameters == parameters
    assert response.warmup_bars == 140
    assert response.warmup_requested == 600
    assert response.history.history_complete
    assert len(response.history.bars) == len(response.points) == 500
    assert any("预热不足" in warning for warning in response.warnings)
    assert response.points[0].ma == "150.5000000000"


async def test_service_invalid_source_ohlc():
    source = source_history(2)
    source.bars[0].open = "NaN"
    reader = SimpleNamespace(get_history=AsyncMock(return_value=source))
    with pytest.raises(AppError) as error:
        await IndicatorService(reader).calculate_daily(IndicatorRequest(symbol="US:AAPL"))
    assert error.value.status == 503


async def test_api_public_readonly_and_validation():
    reader = SimpleNamespace(get_history=AsyncMock(return_value=source_history(5)))
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router)
    app.state.indicator_service = IndicatorService(reader)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/v1/indicators/daily", json={"symbol": "US:AAPL"})
        assert response.status_code == 200
        assert response.json()["algorithm_version"] == "daily-v1"
        assert response.json()["observation_only"] is True
        for body in ({"symbol": "US:AAPL", "bars": []}, {"symbol": "US:AAPL", "limit": True}):
            failure = await client.post("/api/v1/indicators/daily", json=body)
            assert failure.status_code == 422
            assert failure.json()["code"] == "VALIDATION_ERROR"
        assert (await client.get("/api/v1/indicators/daily")).status_code == 405
    assert reader.get_history.await_count == 1
    schema = app.openapi()
    operation = schema["paths"]["/api/v1/indicators/daily"]["post"]
    assert not operation.get("security")
    assert "422" in operation["responses"]
