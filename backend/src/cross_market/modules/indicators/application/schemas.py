from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from cross_market.modules.market_data.application.history_schemas import (
    HistoryAdjustment,
    HistoryResponse,
)


class IndicatorParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ma_period: int = Field(default=10, strict=True, ge=2, le=120)
    macd_fast: int = Field(default=6, strict=True, ge=2, le=60)
    macd_slow: int = Field(default=13, strict=True, ge=3, le=120)
    macd_signal: int = Field(default=5, strict=True, ge=2, le=60)
    kdj_lookback: int = Field(default=13, strict=True, ge=2, le=120)
    kdj_k: int = Field(default=5, strict=True, ge=2, le=60)
    kdj_d: int = Field(default=5, strict=True, ge=2, le=60)
    atr_period: int = Field(default=14, strict=True, ge=2, le=120)

    @model_validator(mode="after")
    def ordered_macd(self):
        if self.macd_fast >= self.macd_slow:
            raise ValueError("macd_fast必须小于macd_slow")
        return self


class IndicatorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(strict=True, min_length=1, max_length=40)
    limit: int = Field(default=120, strict=True, ge=1, le=500)
    adjustment: HistoryAdjustment = "raw"
    parameters: IndicatorParameters = Field(default_factory=IndicatorParameters)

    @field_validator("symbol")
    @classmethod
    def nonempty_symbol(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("证券代码不能为空")
        return value


class IndicatorPoint(BaseModel):
    date: date
    ma: str | None
    dif: str | None
    dea: str | None
    macd: str | None
    k: str | None
    d: str | None
    j: str | None
    atr: str | None


class DailyIndicatorsResponse(BaseModel):
    history: HistoryResponse
    parameters: IndicatorParameters
    algorithm_version: Literal["daily-v1"] = "daily-v1"
    parameter_hash: str
    source_bars: int
    warmup_bars: int
    warmup_requested: int
    visible_bars: int
    points: list[IndicatorPoint]
    as_of: date | None
    calculated_at: datetime
    warnings: list[str]
    observation_only: Literal[True] = True
    formula_notes: list[str]
