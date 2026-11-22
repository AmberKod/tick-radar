import asyncio
from datetime import UTC, datetime, timedelta
from time import monotonic

import httpx

from cross_market.modules.market_data.application.minute_schemas import (
    MinuteBar,
    MinuteHistoryResponse,
)
from cross_market.modules.market_data.domain.quotes import provider_symbol
from cross_market.modules.market_data.infrastructure.tencent_minute import (
    MinuteSourceFailure,
    TencentMinuteSource,
)
from cross_market.shared.config import Settings
from cross_market.shared.exceptions import AppError


class MinuteHistoryService:
    def __init__(self, client: httpx.AsyncClient, settings: Settings):
        self.source = TencentMinuteSource(client)
        self.settings = settings
        self._cache: dict[str, tuple[float, datetime, list[MinuteBar]]] = {}
        self._lock = asyncio.Lock()

    def _present(self, symbol, limit, checked_at, bars):
        cutoff = datetime.now(UTC) - timedelta(minutes=15)
        eligible = [bar for bar in bars if bar.timestamp <= cutoff]
        excluded = len(bars) - len(eligible)
        visible = [bar.model_copy(deep=True) for bar in eligible[-limit:]]
        latest = visible[-1].timestamp if visible else None
        complete = len(visible) >= limit
        return MinuteHistoryResponse(
            symbol=symbol, bars=visible, requested_limit=limit, actual_count=len(visible),
            earliest_timestamp=visible[0].timestamp if visible else None,
            latest_timestamp=latest, checked_at=checked_at, data_as_of=latest,
            history_complete=complete,
            coverage_reason=(
                "已达到请求条数，仅表示本次条数覆盖，不代表连续、无缺失或完整历史"
                if complete else "可呈现分钟历史少于请求条数，覆盖不足"
            ),
            warnings=[
                "15分钟历史仅供观察，非实时行情；不拼接实时报价",
                "供应商来源：腾讯公开分钟接口（tencent_minute_public）",
                "复权口径vendor_unverified：接口无复权参数，不能确认不复权或前后复权",
                "Asia/Shanghai时区由市场推断；供应商时间标签起止语义未经核实",
                "仅呈现时间标签不晚于当前UTC减15分钟的Bar，不保证Bar已最终完成",
                f"本次排除{excluded}根近期或未来时间标签Bar",
                "来源授权及长期存储许可尚未核实；仅使用60秒进程缓存",
                "成交量保留供应商原始字符串，股或手等单位尚未核实",
                "不补午休、夜间或缺失Bar，不保证历史连续；不按日历丢弃供应商记录",
            ],
        )

    async def get_history(self, symbol: str, limit: int = 120) -> MinuteHistoryResponse:
        provider = provider_symbol(symbol)
        if type(limit) is not int or not 1 <= limit <= 320:
            raise ValueError("分钟历史数量必须为1至320")
        if not provider.startswith(("sh", "sz")):
            raise AppError(
                422, "MINUTE_MARKET_UNSUPPORTED",
                "分钟历史仅支持已实测沪深CN市场；港美股及未有效覆盖的北京BSE暂不支持",
            )

        def cached():
            entry = self._cache.get(provider)
            if entry and monotonic() - entry[0] < 60:
                return self._present(symbol, limit, entry[1], entry[2])
            return None

        result = cached()
        if result is not None:
            return result
        try:
            await asyncio.wait_for(self._lock.acquire(), timeout=1)
        except TimeoutError as exc:
            raise AppError(503, "MINUTE_HISTORY_BUSY", "分钟历史查询繁忙，请稍后重试") from exc
        try:
            result = cached()
            if result is not None:
                return result
            try:
                bars = await self.source.fetch(provider)
            except MinuteSourceFailure as exc:
                raise AppError(
                    503, "MINUTE_HISTORY_UNAVAILABLE", "分钟历史数据暂不可用或未覆盖"
                ) from exc
            checked_at = datetime.now(UTC)
            if len(self._cache) >= 32:
                self._cache.pop(next(iter(self._cache)))
            self._cache[provider] = (monotonic(), checked_at, bars)
            return self._present(symbol, limit, checked_at, bars)
        finally:
            self._lock.release()
