from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal, DecimalException, InvalidOperation, localcontext
from typing import Protocol

from cross_market.modules.market_data.application.schemas import QuoteDTO, QuotesResponse
from cross_market.modules.portfolio.application.valuation_schemas import (
    PortfolioValuationResponse,
    ValuedPortfolioPosition,
)


class SnapshotService(Protocol):
    async def snapshot(self, symbols: list[str]) -> QuotesResponse: ...


def money(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_EVEN), "f")


def usable_price(quote: QuoteDTO, symbol: str, currency: str, checked_at: datetime):
    if quote.symbol != symbol or quote.currency != currency:
        return None
    if quote.quality_status in {"INVALID", "UNAVAILABLE"} or quote.received_at is None:
        return None
    if quote.received_at.tzinfo is None:
        return None
    age = (checked_at - quote.received_at).total_seconds()
    if not 0 <= age <= 3600:
        return None
    try:
        raw = quote.price
        if not isinstance(raw, str) or len(raw) > 64:
            return None
        price = Decimal(raw)
        return price if price.is_finite() and 0 < price < Decimal("1e24") else None
    except (InvalidOperation, ValueError, TypeError):
        return None


async def value_summary(summary, quote_service: SnapshotService) -> PortfolioValuationResponse:
    checked_at = datetime.now(UTC)
    warnings = list(summary.warnings)
    warnings.append("仅供观察估值；报价延迟未知，不能视为实时价格")
    current = [position for position in summary.positions if Decimal(position.quantity) > 0]
    symbols = list(dict.fromkeys(position.symbol for position in current))[:50]
    quotes = {}
    if symbols:
        try:
            snapshot = await quote_service.snapshot(symbols)
            checked_at = datetime.now(UTC)
            quotes = {quote.symbol: quote for quote in snapshot.quotes if quote.symbol in symbols}
        except Exception:
            # 缓存故障不能影响账本读取，也不向调用方泄露连接信息。
            warnings.append("报价缓存暂不可用，账本仍可查看；估值缺失")
    with localcontext() as context:
        context.prec = 80
        known_value = Decimal(0)
        known_pnl = Decimal(0)
        valued_count = 0
        positions = []
        for position in current:
            values = {
                field: getattr(position, field)
                for field in (
                    "security_id", "symbol", "name", "currency", "quantity", "total_cost",
                    "average_cost", "realized_pnl", "dividend_income",
                )
            }
            quote = quotes.get(position.symbol)
            price = (
                usable_price(quote, position.symbol, position.currency, checked_at)
                if quote is not None and position.currency == summary.account.currency
                else None
            )
            if position.symbol not in symbols:
                warnings.append(f"{position.symbol}：超出50个标的快照覆盖上限，未估值")
            if quote is not None:
                quote = quote.model_copy(deep=True)
                quote.delay_status = "UNKNOWN"
                if quote.received_at is not None and quote.received_at.tzinfo is not None:
                    age = (checked_at - quote.received_at).total_seconds()
                    quote.cache_age_seconds = max(0, age)
                    if age < 0:
                        warnings.append(f"{position.symbol}：报价接收时间在未来，未估值")
                if quote.quality_status == "STALE" or quote.error is not None:
                    warnings.append(f"{position.symbol}：使用陈旧或来源报错的观察报价，非实时")
                warnings.extend(f"{position.symbol}：{warning}" for warning in quote.warnings)
            if price is not None:
                try:
                    market_value = Decimal(position.quantity) * price
                    pnl = market_value - Decimal(position.total_cost)
                    price_text = money(price)
                    market_value_text = money(market_value)
                    pnl_text = money(pnl)
                except DecimalException:
                    price = None
            if price is None:
                warnings.append(f"{position.symbol}：缺少同币种有效观察报价，未估值")
                positions.append(ValuedPortfolioPosition(**values, quote=quote))
                continue
            known_value += market_value
            known_pnl += pnl
            valued_count += 1
            positions.append(ValuedPortfolioPosition(
                **values, quote=quote, price=price_text, market_value=market_value_text,
                unrealized_pnl=pnl_text,
            ))
        complete = valued_count == len(current)
        return PortfolioValuationResponse(
            account_id=summary.account.id,
            currency=summary.account.currency,
            cash_balance=summary.cash_balance,
            known_market_value=money(known_value),
            market_value=money(known_value) if complete else None,
            unrealized_pnl=money(known_pnl) if complete else None,
            net_asset_value=(
                money(Decimal(summary.cash_balance) + known_value) if complete else None
            ),
            valued_positions=valued_count,
            total_positions=len(current),
            complete=complete,
            positions=positions,
            checked_at=checked_at,
            warnings=list(dict.fromkeys(warnings)),
        )
