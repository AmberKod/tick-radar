from cross_market.modules.market_data.domain.quotes import infer_exchange, provider_symbol


def resolve_exchange(symbol: str, exchange: str | None) -> str:
    provider_symbol(symbol)
    inferred = infer_exchange(symbol)
    if symbol.startswith("US:"):
        if exchange not in {"NASDAQ", "NYSE", "AMEX"}:
            raise ValueError("美股必须明确选择交易所")
        return exchange
    if exchange is not None and exchange != inferred:
        raise ValueError("证券代码与交易所不匹配")
    return inferred
