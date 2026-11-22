import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from time import monotonic

TASK_KEY = "health:worker:task:quote_collector"
WRITE_STATUS = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
local payload = cjson.decode(ARGV[2])
if payload.state ~= 'success' then
    local previous = redis.call('GET', KEYS[2])
    if previous then
        local ok, decoded = pcall(cjson.decode, previous)
        if ok then payload.last_success_at = decoded.last_success_at or cjson.null end
    end
end
redis.call('SET', KEYS[2], cjson.encode(payload), 'EX', ARGV[3])
return 1
"""


def valid_quote(quote) -> bool:
    if quote.error is not None or quote.quality_status not in {"UNKNOWN", "MARKET_CLOSED"}:
        return False
    try:
        price = Decimal(str(quote.price))
        return price.is_finite() and price > 0
    except (InvalidOperation, ValueError, TypeError):
        return False


async def collect_once(
    session_factory, list_targets, quote_service, limit, *, publication_guard=None
):
    async with asyncio.timeout(3):
        async with session_factory() as session:
            symbols = await list_targets(session, limit=limit)
    symbols = list(dict.fromkeys(symbols))[:limit]
    if not symbols:
        return "idle", 0, 0, "NO_SYMBOLS"
    async with asyncio.timeout(6):
        response = await quote_service.get_quotes(
            symbols, refresh=True, publication_guard=publication_guard
        )
    # 按请求标的核对，缺项不能记作整轮成功。
    quotes = {quote.symbol: quote for quote in response.quotes}
    errors = sum(symbol not in quotes or not valid_quote(quotes[symbol]) for symbol in symbols)
    return (
        ("partial" if errors else "success"),
        len(symbols),
        errors,
        ("QUOTE_INCOMPLETE" if errors else "OBSERVATION_UPDATED"),
    )


async def quote_collector(runtime, *, session_factory, list_targets, quote_service):
    settings = runtime.settings
    interval = settings.quote_refresh_interval_seconds
    limit = min(settings.quote_max_symbols, 50)
    while not runtime.stop_event.is_set():
        started = monotonic()
        try:
            async with asyncio.timeout(min(20, interval)):
                state, count, errors, code = await collect_once(
                    session_factory,
                    list_targets,
                    quote_service,
                    limit,
                    publication_guard=(settings.worker_lock_key, runtime.owner),
                )
        except TimeoutError:
            state, count, errors, code = "error", 0, 1, "COLLECTION_TIMEOUT"
        except Exception:
            # 异常可能包含连接口令或供应商原文，诊断只记录稳定代码。
            state, count, errors, code = "error", 0, 1, "COLLECTION_FAILED"
        checked_at = datetime.now(UTC).isoformat()
        payload = {
            "task_name": "quote_collector",
            "state": state,
            "last_success_at": checked_at if state == "success" else None,
            "checked_at": checked_at,
            "error_count": errors,
            "symbol_count": count,
            "duration_ms": round((monotonic() - started) * 1000),
            "last_error": code if state in {"error", "partial"} else None,
            "detail": code,
        }
        written = await runtime.redis.eval(
            WRITE_STATUS,
            2,
            settings.worker_lock_key,
            TASK_KEY,
            runtime.owner,
            json.dumps(payload),
            max(interval * 4, 120),
        )
        if not written:
            raise RuntimeError("任务所有权已失效")
        try:
            await asyncio.wait_for(runtime.stop_event.wait(), interval)
        except TimeoutError:
            pass
