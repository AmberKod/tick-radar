from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field


class MinuteBar(BaseModel):
    timestamp: AwareDatetime
    source_time_raw: str = Field(max_length=64)
    open: str = Field(max_length=64)
    high: str = Field(max_length=64)
    low: str = Field(max_length=64)
    close: str = Field(max_length=64)
    volume: str = Field(max_length=64)


class MinuteHistoryResponse(BaseModel):
    symbol: str
    market: Literal["CN"] = "CN"
    currency: Literal["CNY"] = "CNY"
    source: Literal["tencent_minute_public"] = "tencent_minute_public"
    period: Literal["m15"] = "m15"
    adjustment: Literal["vendor_unverified"] = "vendor_unverified"
    timezone: Literal["Asia/Shanghai"] = "Asia/Shanghai"
    timestamp_semantics: Literal["VENDOR_BAR_LABEL_UNVERIFIED"] = "VENDOR_BAR_LABEL_UNVERIFIED"
    bars: list[MinuteBar]
    requested_limit: int
    actual_count: int
    earliest_timestamp: AwareDatetime | None
    latest_timestamp: AwareDatetime | None
    checked_at: AwareDatetime
    data_as_of: AwareDatetime | None
    observation_only: Literal[True] = True
    history_complete: bool
    coverage_reason: str
    warnings: list[str]
