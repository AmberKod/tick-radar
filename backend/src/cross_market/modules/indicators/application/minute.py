import asyncio
import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol

from cross_market.modules.indicators.application.minute_schemas import (
    MinuteIndicatorPoint,
    MinuteIndicatorRequest,
    MinuteIndicatorsResponse,
)
from cross_market.modules.indicators.domain.calculations import Bar, Params, calculate_intraday
from cross_market.modules.market_data.application.minute_schemas import MinuteHistoryResponse
from cross_market.shared.exceptions import AppError


class MinuteHistoryReader(Protocol):
    async def get_history(self, symbol: str, limit: int = 120) -> MinuteHistoryResponse: ...


class MinuteIndicatorService:
    def __init__(self, minute_history_service: MinuteHistoryReader):
        self.history_service = minute_history_service

    async def calculate_minute(self, request: MinuteIndicatorRequest) -> MinuteIndicatorsResponse:
        parameters = request.parameters.model_dump()
        p = Params(**parameters)
        warmup_requested = max(
            p.ma_period, p.macd_slow + p.macd_signal - 1, p.kdj_lookback, p.atr_period,
            5 * max(p.macd_slow, p.kdj_k, p.kdj_d, p.atr_period),
        )
        source = await self.history_service.get_history(
            request.symbol, min(320, request.limit + warmup_requested)
        )
        try:
            bars = []
            for item in source.bars:
                opening = Decimal(item.open)
                high, low, close = Decimal(item.high), Decimal(item.low), Decimal(item.close)
                if not opening.is_finite() or opening <= 0 or not low <= opening <= high:
                    raise ValueError("分钟开盘价无效")
                bars.append(Bar(item.timestamp, high, low, close))
            points = await asyncio.to_thread(calculate_intraday, bars, p)
        except (ValueError, InvalidOperation) as exc:
            raise AppError(503, "INDICATOR_HISTORY_INVALID", "指标源分钟数据无效") from exc
        visible = source.bars[-request.limit:]
        latest = visible[-1].timestamp if visible else None
        complete = len(visible) >= request.limit
        history = source.model_copy(deep=True, update={
            "bars": [item.model_copy(deep=True) for item in visible],
            "actual_count": len(visible), "requested_limit": request.limit,
            "latest_timestamp": latest,
            "earliest_timestamp": visible[0].timestamp if visible else None,
            "data_as_of": latest, "history_complete": complete,
            "coverage_reason": (
                "已达到展示请求条数，不代表历史连续、无缺失或完整"
                if complete else "展示分钟Bar少于请求条数，覆盖不足"
            ),
        })
        warmup_bars = max(0, len(bars) - request.limit)
        warnings = list(source.warnings)
        if not source.history_complete:
            warnings.append("源历史未达到预取请求条数，指标预热历史可能不足")
        if warmup_bars < warmup_requested:
            warnings.append(
                f"预热不足：期望{warmup_requested}根，实际裁掉{warmup_bars}根；"
                "320根预取上限或源历史覆盖可能限制预热"
            )
        warnings.extend([
            "指标仅供观察，不产生交易信号或告警；预热不保证递归指标绝对收敛",
            "复权口径vendor_unverified，跨除权日的指标可靠性尚未核实",
            "不同limit可能改变额外历史与递归种子，重叠时间结果可能存在微小差异",
        ])
        canonical = json.dumps(parameters, sort_keys=True, separators=(",", ":"))
        mapped = []
        for point in points[-request.limit:]:
            values = asdict(point)
            values["timestamp"] = values.pop("date")
            mapped.append(MinuteIndicatorPoint(**values))
        return MinuteIndicatorsResponse(
            history=history, parameters=request.parameters.model_copy(deep=True),
            parameter_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            source_bars=len(bars), warmup_bars=warmup_bars, warmup_requested=warmup_requested,
            visible_bars=len(visible), points=mapped, as_of=latest,
            calculated_at=datetime.now(UTC), warnings=warnings,
            formula_notes=[
                "与日线共用Decimal公式引擎，以真实UTC分钟时间为键，不按日期合并",
                "SMA：n根收盘均值；EMA：前n根均值作种子，alpha=2/(n+1)",
                "DIF=EMA快-EMA慢；DEA以signal个有效DIF均值为种子；MACD=2*(DIF-DEA)",
                "KDJ：滚动高低价RSV，相等取50，K/D初值50；J=3K-2D不截断",
                "TR首根=高-低，之后兼顾前收缺口；ATR均值种子后Wilder递推",
                "Decimal精度80，10位小数、ROUND_HALF_EVEN，规范负零；未成熟值为空",
                "周期按供应商实际返回Bar计数，不补午休、夜间或缺失Bar",
            ],
        )
