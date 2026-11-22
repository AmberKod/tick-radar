import asyncio
from datetime import UTC, datetime
from time import monotonic

from cross_market.modules.market_data.application.schemas import (
    QuoteDTO,
    QuoteError,
    QuotesResponse,
)
from cross_market.modules.market_data.domain.quotes import (
    CURRENCIES,
    market_status,
    parse_record,
    provider_symbol,
)
from cross_market.modules.market_data.infrastructure.cache import LEASE_SECONDS, RedisQuoteCache
from cross_market.modules.market_data.infrastructure.tencent import ProviderFailure, TencentSource

# Redis故障时，同进程所有服务实例共享保守预算。
_local_budget_window = -1
_local_budget_count = 0


def take_local_budget() -> bool:
    global _local_budget_window, _local_budget_count
    window = int(monotonic() // 60)
    if window != _local_budget_window:
        _local_budget_window, _local_budget_count = window, 0
    if _local_budget_count >= 10:
        return False
    _local_budget_count += 1
    return True


class QuoteService:
    def __init__(self, client, redis, settings):
        self.source = TencentSource(client)
        self.cache = RedisQuoteCache(redis)
        self.settings = settings
        self._lock = asyncio.Lock()
        self._local: dict[str, QuoteDTO] = {}
        self._attempts: dict[str, float] = {}

    @staticmethod
    def empty(symbol: str, code: str, message: str) -> QuoteDTO:
        market = symbol.split(":")[0]
        return QuoteDTO(
            symbol=symbol,
            market=market,
            currency=CURRENCIES[market],
            provider_symbol=provider_symbol(symbol),
            error=QuoteError(code=code, message=message),
        )

    async def _read(self, symbol: str) -> QuoteDTO | None:
        payload = await self.cache.read(symbol)
        if not payload:
            return None
        quote = QuoteDTO.model_validate_json(payload)
        if quote.symbol != symbol:
            raise ValueError("缓存证券标识不匹配")
        return quote

    def _due(self, quote: QuoteDTO | None, refresh: bool) -> bool:
        if quote is None:
            return True
        if refresh:
            return True
        stamp = quote.attempted_at if quote.error else quote.received_at
        interval = LEASE_SECONDS if quote.error else self.settings.quote_refresh_interval_seconds
        return stamp is None or (datetime.now(UTC) - stamp).total_seconds() >= interval

    async def get_quotes(
        self,
        symbols: list[str],
        refresh: bool = False,
        *,
        publication_guard: tuple[str, str] | None = None,
    ) -> QuotesResponse:
        if not 1 <= len(symbols) <= min(50, self.settings.quote_max_symbols):
            raise ValueError("单次请求代码数量超出限制")
        for symbol in symbols:
            provider_symbol(symbol)
        if not self.settings.market_observation_enabled:
            return QuotesResponse(
                checked_at=datetime.now(UTC),
                quotes=[
                    self.empty(symbol, "OBSERVATION_DISABLED", "报价查询已关闭")
                    for symbol in symbols
                ],
            )
        quotes = {}
        candidates = []
        cache_failed = False
        for symbol in dict.fromkeys(symbols):
            quote = self._local.get(symbol)
            try:
                quote = await self._read(symbol) or quote
            except Exception:
                cache_failed = True
            if (
                quote
                and quote.received_at
                and (datetime.now(UTC) - quote.received_at).total_seconds() > 3600
            ):
                quote = None
            quotes[symbol] = quote
            if self._due(quote, refresh) and (
                monotonic() - self._attempts.get(symbol, -float("inf")) >= LEASE_SECONDS
            ):
                candidates.append(symbol)
        # 缓存读取不进入网络请求锁；忙时立即返回现有报价。
        if candidates and not self._lock.locked():
            await self._lock.acquire()
            try:
                pending = {}
                for symbol in candidates:
                    if monotonic() - self._attempts.get(symbol, -float("inf")) < LEASE_SECONDS:
                        continue
                    try:
                        owner = await self.cache.acquire(symbol)
                        # 获取租约前缓存可能已由另一进程更新，失败回退必须基于最新值。
                        quotes[symbol] = await self._read(symbol) or quotes[symbol]
                        if owner is None:
                            continue
                    except Exception:
                        cache_failed = True
                        owner = None
                        if publication_guard is not None:
                            # Worker 无法确认实例所有权时，不通过本地降级绕过发布约束。
                            continue
                    self._attempts[symbol] = monotonic()
                    pending[symbol] = owner
                if pending:
                    try:
                        allowed = await self.cache.take_budget()
                    except Exception:
                        cache_failed = True
                        allowed = take_local_budget()
                    if allowed:
                        try:
                            records, received_at = await self.source.fetch(list(pending))
                            failure = None
                        except ProviderFailure as exc:
                            records, received_at, failure = {}, None, exc.code
                    else:
                        records, received_at, failure = {}, None, "UPSTREAM_BUDGET_EXCEEDED"
                    attempted_at = datetime.now(UTC)
                    for symbol, owner in pending.items():
                        old = quotes[symbol]
                        key = provider_symbol(symbol)
                        quote = self.empty(
                            symbol, failure or "SYMBOL_UNAVAILABLE", "供应商未返回可用报价"
                        )
                        quote.attempted_at = attempted_at
                        if failure is None and key in records:
                            try:
                                fields = parse_record(symbol, records[key])
                                quote = quote.model_copy(
                                    update={
                                        **fields,
                                        "received_at": received_at,
                                        "quality_status": "UNKNOWN",
                                        "error": None,
                                    }
                                )
                            except ValueError:
                                quote.quality_status = "INVALID"
                                quote.error = QuoteError(
                                    code="INVALID_PROVIDER_RECORD", message="供应商报价无效"
                                )
                        if quote.error and old and old.price:
                            quote = old.model_copy(
                                deep=True,
                                update={
                                    "quality_status": "STALE",
                                    "error": quote.error,
                                    "attempted_at": attempted_at,
                                },
                            )
                        published = owner is None
                        if owner is not None:
                            try:
                                published = await self.cache.write(
                                    symbol,
                                    quote.model_dump_json(),
                                    owner=owner,
                                    ttl=3600 if quote.price else LEASE_SECONDS,
                                    publication_guard=publication_guard,
                                )
                            except Exception:
                                cache_failed = True
                        if published:
                            quotes[symbol] = quote
                            self._local[symbol] = quote
                        else:
                            # 失去owner或无法确认写入时，不把旧请求结果放进本地缓存。
                            try:
                                quotes[symbol] = await self._read(symbol) or old
                                if quotes[symbol] is not None:
                                    self._local[symbol] = quotes[symbol]
                            except Exception:
                                cache_failed = True
            finally:
                self._lock.release()
        checked_at = datetime.now(UTC)
        result = []
        for symbol in symbols:
            quote = quotes[symbol]
            if quote is None:
                quote = self.empty(symbol, "REFRESH_THROTTLED", "刷新正在进行，请稍后重试")
            quote = quote.model_copy(deep=True)
            quote.market_status = market_status(quote.market, checked_at)
            if quote.received_at:
                quote.cache_age_seconds = max(0, (checked_at - quote.received_at).total_seconds())
                quote.quality_status = (
                    "STALE" if quote.error or quote.cache_age_seconds > 180 else quote.market_status
                )
            if cache_failed:
                quote.warnings.append("缓存不可用，本次查询使用进程内降级缓存")
            result.append(quote)
        return QuotesResponse(quotes=result, checked_at=checked_at)
