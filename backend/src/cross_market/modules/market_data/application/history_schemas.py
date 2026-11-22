from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

HistoryAdjustment = Literal["raw", "qfq", "hfq"]


class HistoryBar(BaseModel):
    date: date
    open: str = Field(max_length=64)
    high: str = Field(max_length=64)
    low: str = Field(max_length=64)
    close: str = Field(max_length=64)
    volume: str = Field(max_length=64)


class HistoryResponse(BaseModel):
    symbol: str
    market: Literal["CN", "HK", "US"]
    currency: Literal["CNY", "HKD", "USD"]
    source: Literal["tencent_history_public"] = "tencent_history_public"
    adjustment: HistoryAdjustment
    period: Literal["day"] = "day"
    bars: list[HistoryBar]
    requested_limit: int
    actual_count: int
    latest_date: date | None
    earliest_date: date | None
    checked_at: datetime
    data_as_of: date | None
    observation_only: Literal[True] = True
    warnings: list[str]
    history_complete: bool
    coverage_reason: str
