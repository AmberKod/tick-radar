import sys
from datetime import UTC, datetime, timedelta
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cross_market.apps.worker.main import list_collection_targets
from cross_market.modules.market_data.application.schemas import (
    QuoteDTO,
    QuoteError,
    QuotesResponse,
)
from cross_market.modules.portfolio.application.valuation import value_summary


def position(symbol="US:AAPL", **changes):
    values = dict(
        security_id=symbol, symbol=symbol, name="测试证券", currency="USD", quantity="3",
        total_cost="0.2", average_cost="0.06666667", realized_pnl="0", dividend_income="0",
    )
    return SimpleNamespace(**(values | changes))


def summary(positions):
    return SimpleNamespace(
        account=SimpleNamespace(id="account", currency="USD"), cash_balance="1.00000000",
        positions=positions, warnings=["账本提示"],
    )


def quote(symbol="US:AAPL", **changes):
    values = dict(
        symbol=symbol, market="US", currency="USD", provider_symbol="usAAPL", price="0.1",
        quality_status="UNKNOWN", received_at=datetime.now(UTC) - timedelta(seconds=5),
        source_time_raw="供应商原始时刻", warnings=[],
    )
    return QuoteDTO(**(values | changes))


def service(quotes):
    return SimpleNamespace(snapshot=AsyncMock(return_value=QuotesResponse(
        quotes=quotes, checked_at=datetime.now(UTC),
    )))


async def test_decimal_exact_and_source_metadata():
    source = quote()
    snapshots = service([source])
    result = await value_summary(summary([position()]), snapshots)
    assert result.complete
    assert result.market_value == "0.30000000"
    assert result.unrealized_pnl == "0.10000000"
    assert result.net_asset_value == "1.30000000"
    assert result.positions[0].quote.source == "tencent_public"
    assert result.positions[0].quote.source_time_raw == "供应商原始时刻"
    assert result.positions[0].quote.received_at == source.received_at
    assert result.positions[0].quote.delay_status == "UNKNOWN"
    snapshots.snapshot.assert_awaited_once_with(["US:AAPL"])


async def test_one_missing_price_nulls_totals():
    result = await value_summary(
        summary([position(), position("US:MSFT")]), service([quote()]),
    )
    assert not result.complete
    assert result.known_market_value == "0.30000000"
    assert result.market_value is result.unrealized_pnl is result.net_asset_value is None
    assert result.positions[1].quote is None
    assert result.valued_positions == 1


async def test_empty_or_closed_positions_do_not_read_cache():
    snapshots = service([])
    result = await value_summary(summary([position(quantity="0")]), snapshots)
    assert result.complete and result.positions == []
    assert result.market_value == result.unrealized_pnl == "0.00000000"
    assert result.net_asset_value == "1.00000000"
    snapshots.snapshot.assert_not_awaited()


@pytest.mark.parametrize("changes", [
    {"symbol": "US:MSFT"}, {"currency": "HKD"}, {"price": "NaN"}, {"price": "Infinity"},
    {"price": "0"}, {"price": "-1"}, {"price": "1e999999999"}, {"price": "1e80"},
    {"received_at": None}, {"quality_status": "INVALID"},
    {"quality_status": "UNAVAILABLE"},
    {"received_at": datetime.now(UTC) + timedelta(days=1)},
    {"received_at": datetime.now(UTC) - timedelta(seconds=3601)},
])
async def test_unusable_quotes_never_become_zero(changes):
    result = await value_summary(summary([position()]), service([quote(**changes)]))
    assert not result.complete
    assert result.positions[0].price is None
    assert result.market_value is None
    assert result.known_market_value == "0.00000000"


async def test_stale_source_error_keeps_price_and_warning():
    result = await value_summary(summary([position()]), service([quote(
        quality_status="STALE", error=QuoteError(code="SOURCE_FAILED", message="源不可用"),
    )]))
    assert result.complete
    assert result.positions[0].quote.error.code == "SOURCE_FAILED"
    assert any("陈旧" in warning and "非实时" in warning for warning in result.warnings)


async def test_cache_failure_preserves_ledger():
    snapshots = SimpleNamespace(snapshot=AsyncMock(side_effect=TimeoutError("secret")))
    result = await value_summary(summary([position()]), snapshots)
    assert result.cash_balance == "1.00000000"
    assert result.positions[0].total_cost == "0.2"
    assert result.positions[0].quote is None
    assert any("缓存暂不可用" in warning for warning in result.warnings)
    assert "secret" not in str(result.warnings)


async def test_coverage_is_limited_to_fifty():
    positions = [position(f"US:T{i}") for i in range(51)]
    snapshots = service([quote(p.symbol) for p in positions])
    result = await value_summary(summary(positions), snapshots)
    assert len(snapshots.snapshot.call_args.args[0]) == 50
    assert result.total_positions == 51 and result.valued_positions == 50
    assert not result.complete and result.positions[-1].quote is None
    assert any("覆盖上限" in warning for warning in result.warnings)


async def test_round_half_even_at_eight_places():
    result = await value_summary(summary([position(quantity="1", total_cost="0")]), service([
        quote(price="1.000000005"),
    ]))
    assert result.market_value == "1.00000000"


@pytest.mark.parametrize("holdings,watchlist,expected", [
    (["US:B", "US:A"], ["US:A", "US:C", "US:D"], ["US:B", "US:A", "US:C"]),
    ([], ["US:A", "US:B"], ["US:A", "US:B"]),
])
async def test_worker_prioritizes_holdings_and_deduplicates(
    monkeypatch, holdings, watchlist, expected,
):
    portfolio = ModuleType("cross_market.modules.portfolio.application.summary")
    portfolio.list_quote_targets = AsyncMock(return_value=holdings)
    monkeypatch.setitem(sys.modules, portfolio.__name__, portfolio)
    watchlist_targets = AsyncMock(return_value=watchlist)
    monkeypatch.setattr(
        "cross_market.modules.watchlist.application.service.list_quote_targets", watchlist_targets,
    )
    alerts = ModuleType("cross_market.modules.alerts.application.service")
    alerts.list_quote_targets = AsyncMock(return_value=[])
    monkeypatch.setitem(sys.modules, alerts.__name__, alerts)
    session = object()
    assert await list_collection_targets(session, limit=3) == expected
    portfolio.list_quote_targets.assert_awaited_once_with(session, limit=3)
    watchlist_targets.assert_awaited_once_with(session, limit=3)
