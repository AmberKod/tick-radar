from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from cross_market.modules.indicators.application.schemas import IndicatorParameters
from cross_market.modules.market_data.application.minute_schemas import MinuteHistoryResponse


class MinuteIndicatorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(strict=True, min_length=1, max_length=40)
    limit: int = Field(default=120, strict=True, ge=1, le=250)
    parameters: IndicatorParameters = Field(default_factory=IndicatorParameters)


class MinuteIndicatorPoint(BaseModel):
    timestamp: AwareDatetime
    ma: str | None
    dif: str | None
    dea: str | None
    macd: str | None
    k: str | None
    d: str | None
    j: str | None
    atr: str | None


class MinuteIndicatorsResponse(BaseModel):
    history: MinuteHistoryResponse
    parameters: IndicatorParameters
    algorithm_version: Literal["m15-v1"] = "m15-v1"
    parameter_hash: str
    source_bars: int
    warmup_bars: int
    warmup_requested: int
    visible_bars: int
    points: list[MinuteIndicatorPoint]
    as_of: AwareDatetime | None
    calculated_at: AwareDatetime
    warnings: list[str]
    formula_notes: list[str]
    observation_only: Literal[True] = True
