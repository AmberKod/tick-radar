import re
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from zoneinfo import ZoneInfo

TIMEZONES = {"CN": "Asia/Shanghai", "HK": "Asia/Hong_Kong", "US": "America/New_York"}
CURRENCIES = {"CN": "CNY", "HK": "HKD", "US": "USD"}
WARNING = "观察报价，开市时效尚未验收"


def provider_symbol(symbol: str) -> str:
    market, _, ticker = symbol.partition(":")
    if market == "CN" and re.fullmatch(r"[0-9]{6}", ticker):
        if ticker.startswith(("6", "5")):
            return "sh" + ticker
        if ticker.startswith(("0", "3", "15")):
            return "sz" + ticker
        if ticker.startswith(("4", "8", "92")):
            return "bj" + ticker
    if market == "HK" and re.fullmatch(r"0[0-9]{4}", ticker):
        return "hk" + ticker
    if (
        market == "US"
        and len(ticker) <= 20
        and re.fullmatch(r"[A-Z][A-Z0-9]*(?:[.-][A-Z0-9]+)*", ticker)
    ):
        return "us" + ticker
    raise ValueError("不支持的证券代码")


def infer_exchange(symbol: str) -> str | None:
    key = provider_symbol(symbol)
    return {"sh": "SSE", "sz": "SZSE", "bj": "BSE", "hk": "HKEX"}.get(key[:2])


def positive_decimal(raw: str) -> Decimal:
    if not re.fullmatch(r"[0-9]{1,16}(?:\.[0-9]{1,12})?", raw):
        raise ValueError("价格格式无效")
    number = Decimal(raw)
    if not number.is_finite() or number <= 0:
        raise ValueError("价格必须为正数")
    return number


def parse_record(symbol: str, raw: str) -> dict:
    provider_symbol(symbol)
    market, ticker = symbol.split(":")
    parts = raw.split("~")
    currencies = {part.strip().upper() for part in parts} & {"USD", "CNY", "RMB", "HKD"}
    currencies = {"CNY" if value == "RMB" else value for value in currencies}
    if currencies - {CURRENCIES[market]}:
        raise ValueError("供应商报价币种不匹配")
    if len(parts) < 5:
        raise ValueError("报价记录不完整")
    actual = parts[2]
    provider_exchange = infer_exchange(symbol)
    if market == "US":
        exchanges = {".OQ": "NASDAQ", ".N": "NYSE", ".A": "AMEX"}
        suffix = actual.removeprefix(ticker) if actual.startswith(ticker) else None
        matched = actual == ticker or suffix in exchanges
        provider_exchange = exchanges.get(suffix)
    else:
        matched = actual == ticker
    if not matched or (market in {"HK", "US"} and parts[0] != {"HK": "100", "US": "200"}[market]):
        raise ValueError("供应商证券标识不匹配")
    price, previous = positive_decimal(parts[3]), positive_decimal(parts[4])
    with localcontext() as context:
        context.prec = 80
        change = price - previous
        percent = (change / previous * 100).quantize(Decimal("0.0001"))
    source_time = parts[30].strip() if len(parts) > 30 else ""
    timestamp = None
    if source_time and market != "US":
        for pattern in ("%Y%m%d%H%M%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                timestamp = (
                    datetime.strptime(source_time, pattern)
                    .replace(tzinfo=ZoneInfo(TIMEZONES[market]))
                    .astimezone(UTC)
                )
                break
            except ValueError:
                continue
    return {
        "name": parts[1].strip()[:120] or None,
        "provider_exchange": provider_exchange,
        "price": parts[3],
        "prev_close": parts[4],
        "change": format(change, "f"),
        "change_percent": format(percent, ".4f"),
        "source_time_raw": source_time or None,
        "market_timestamp": timestamp,
        "timestamp_timezone_basis": "MARKET_INFERRED" if timestamp else "UNVERIFIED",
    }
