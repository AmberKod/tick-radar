import asyncio
from datetime import UTC, datetime, timedelta
from time import monotonic
from zoneinfo import ZoneInfo

import httpx

from cross_market.modules.market_data.application.history_schemas import HistoryResponse
from cross_market.modules.market_data.domain.quotes import CURRENCIES, TIMEZONES, provider_symbol
from cross_market.modules.market_data.infrastructure.tencent_history import (
    HistorySourceFailure,
    TencentHistorySource,
)
from cross_market.shared.config import Settings
from cross_market.shared.exceptions import AppError


class HistoryService:
    def __init__(self, client: httpx.AsyncClient, settings: Settings):
        self.source = TencentHistorySource(client)
        self.settings = settings
        self._cache: dict[tuple, tuple[float, HistoryResponse]] = {}
        self._lock = asyncio.Lock()

    async def get_history(
        self, symbol: str, limit: int = 120, adjustment: str = "raw"
    ) -> HistoryResponse:
        provider = provider_symbol(symbol)
        if type(limit) is not int or not 1 <= limit <= 640:
            raise ValueError("历史日线数量必须为1至640")
        if adjustment not in {"raw", "qfq", "hfq"}:
            raise ValueError("历史复权方式无效")
        market = symbol.partition(":")[0]
        if market == "US" and adjustment == "hfq":
            raise AppError(422, "ADJUSTMENT_UNSUPPORTED", "当前历史数据源不支持美股后复权")
        # 本批只呈现当地日期早于今天的历史Bar，避免把仍会变化的当日Bar当成最终日线。
        end = datetime.now(UTC).astimezone(ZoneInfo(TIMEZONES[market])).date() - timedelta(days=1)
        key = (provider, adjustment, limit, end)

        def cached():
            entry = self._cache.get(key)
            if entry and monotonic() - entry[0] < 60:
                return entry[1].model_copy(deep=True)
            return None

        result = cached()
        if result is not None:
            return result
        try:
            await asyncio.wait_for(self._lock.acquire(), timeout=1)
        except TimeoutError as exc:
            raise AppError(503, "HISTORY_BUSY", "历史查询繁忙，请稍后重试") from exc
        try:
            result = cached()
            if result is not None:
                return result
            try:
                async with asyncio.timeout(12):
                    bars = await self.source.fetch(provider, adjustment, limit, end=end)
            except (HistorySourceFailure, TimeoutError) as exc:
                raise AppError(
                    503, "HISTORY_UNAVAILABLE", "历史日线数据暂不可用或该口径未覆盖"
                ) from exc
            latest = bars[-1].date if bars else None
            complete = len(bars) >= limit
            result = HistoryResponse(
                symbol=symbol,
                market=market,
                currency=CURRENCIES[market],
                adjustment=adjustment,
                bars=bars,
                requested_limit=limit,
                actual_count=len(bars),
                latest_date=latest,
                earliest_date=bars[0].date if bars else None,
                checked_at=datetime.now(UTC),
                data_as_of=latest,
                warnings=[
                    "历史日线，仅供观察，非实时行情；不拼接当前报价",
                    "仅包含交易所本地日期早于今天的日线，当日Bar不纳入本批",
                    "供应商来源：腾讯公开历史接口（tencent_history_public）",
                    f"复权口径：{adjustment}（raw不复权、qfq前复权、hfq后复权）",
                    "来源授权及长期存储许可尚未核实；本批只用60秒进程缓存",
                    "成交量保留供应商原始字符串，单位尚未核实",
                    "达到请求根数不代表交易所完整历史、无缺日或公司行动全部正确",
                ],
                history_complete=complete,
                coverage_reason=(
                    "已达到请求条数，仅表示本次条数覆盖，不代表完整上市历史或无缺日"
                    if complete
                    else "供应商返回条数少于请求条数，历史覆盖不足"
                ),
            )
            # 有界缓存，不把历史Bar落到报价key、Pub/Sub或数据库。
            if len(self._cache) >= 32:
                self._cache.pop(next(iter(self._cache)))
            self._cache[key] = (monotonic(), result.model_copy(deep=True))
            return result
        finally:
            self._lock.release()
