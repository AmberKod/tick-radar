import asyncio
import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol

from cross_market.modules.indicators.application.schemas import (
    DailyIndicatorsResponse,
    IndicatorPoint,
    IndicatorRequest,
)
from cross_market.modules.indicators.domain.calculations import Bar, Params, calculate_daily
from cross_market.modules.market_data.application.history_schemas import HistoryResponse
from cross_market.shared.exceptions import AppError


class HistoryReader(Protocol):
    async def get_history(
        self, symbol: str, limit: int = 120, adjustment: str = "raw"
    ) -> HistoryResponse: ...


class IndicatorService:
    def __init__(self, history_service: HistoryReader):
        self.history_service = history_service

    async def calculate_daily(self, request: IndicatorRequest) -> DailyIndicatorsResponse:
        parameters = request.parameters.model_dump()
        p = Params(**parameters)
        warmup_requested = max(
            p.ma_period,
            p.macd_slow + p.macd_signal - 1,
            p.kdj_lookback,
            p.atr_period,
            5 * max(p.macd_slow, p.kdj_k, p.kdj_d, p.atr_period),
        )
        fetch_limit = min(640, request.limit + warmup_requested)
        source = await self.history_service.get_history(
            request.symbol, fetch_limit, request.adjustment
        )
        try:
            bars = []
            for item in source.bars:
                opening = Decimal(item.open)
                high, low, close = Decimal(item.high), Decimal(item.low), Decimal(item.close)
                if not opening.is_finite() or opening <= 0 or not low <= opening <= high:
                    raise ValueError("日线开盘价无效")
                bars.append(Bar(item.date, high, low, close))
            points = await asyncio.to_thread(calculate_daily, bars, p)
        except (ValueError, InvalidOperation) as exc:
            raise AppError(503, "INDICATOR_HISTORY_INVALID", "指标源日线数据无效") from exc
        visible = source.bars[-request.limit :]
        latest = visible[-1].date if visible else None
        complete = len(visible) >= request.limit
        history = source.model_copy(
            deep=True,
            update={
                "bars": [item.model_copy(deep=True) for item in visible],
                "actual_count": len(visible),
                "requested_limit": request.limit,
                "latest_date": latest,
                "earliest_date": visible[0].date if visible else None,
                "data_as_of": latest,
                "history_complete": complete,
                "coverage_reason": (
                    "已达到展示请求条数，不代表完整上市历史或无缺日"
                    if complete
                    else "展示日线少于请求条数，历史覆盖不足"
                ),
            },
        )
        warmup_bars = max(0, len(bars) - request.limit)
        warnings = list(source.warnings)
        if not source.history_complete:
            warnings.append("源历史未达到预取请求条数，指标预热历史可能不足")
        if warmup_bars < warmup_requested:
            warnings.append(
                f"预热不足：期望{warmup_requested}根，实际裁掉{warmup_bars}根；"
                "640根预取上限或源历史覆盖可能限制预热"
            )
        warnings.append("指标仅供观察，不产生交易信号或告警；预热不保证递归指标绝对收敛")
        warnings.append("不同limit可能改变额外历史与递归种子，重叠日期结果可能存在微小差异")
        canonical = json.dumps(parameters, sort_keys=True, separators=(",", ":"))
        return DailyIndicatorsResponse(
            history=history,
            parameters=request.parameters.model_copy(deep=True),
            parameter_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            source_bars=len(bars),
            warmup_bars=warmup_bars,
            warmup_requested=warmup_requested,
            visible_bars=len(visible),
            points=[IndicatorPoint(**asdict(point)) for point in points[-request.limit :]],
            as_of=latest,
            calculated_at=datetime.now(UTC),
            warnings=warnings,
            formula_notes=[
                "SMA：n根收盘价均值，前n-1根为空",
                "EMA：前n根均值作种子，alpha=2/(n+1)，中间不舍入",
                "DIF=EMA快-EMA慢；DEA以signal个有效DIF均值作种子；MACD=2*(DIF-DEA)",
                "KDJ：滚动高低价RSV，高低相等取50；K/D初值50，按各自周期递推；J=3K-2D不截断",
                "TR首根=高-低，之后兼顾昨收缺口；ATR前n个TR均值作种子，之后Wilder递推",
                "Decimal精度80；输出10位小数、ROUND_HALF_EVEN，负零规范为零；未成熟值为空",
            ],
        )
