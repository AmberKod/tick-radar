import re
import unicodedata
from datetime import date
from typing import Any, Literal

from pydantic import AwareDatetime, ConfigDict, Field, field_validator

from cross_market.modules.alerts.application.schemas import UTCResponse, Version
from cross_market.modules.market_calendar.application.schemas import MarketCalendarStatus

CNExchange = Literal["SSE", "SZSE", "BSE"]


class ScheduleCreate(UTCResponse):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(strict=True, min_length=1, max_length=80)
    exchange: CNExchange
    times: list[str] = Field(min_length=1, max_length=8, strict=True)
    message: str = Field(strict=True, min_length=1, max_length=1000)
    grace_seconds: int = Field(default=120, strict=True, ge=30, le=600)
    enabled: bool = Field(default=False, strict=True)

    @field_validator("name", "message", mode="before")
    @classmethod
    def clean_text(cls, value, info):
        if isinstance(value, str):
            if any(
                unicodedata.category(c).startswith("C")
                and not (info.field_name == "message" and c == "\n")
                for c in value
            ):
                raise ValueError("文本不可含控制字符（内容允许换行）")
            return value.strip()
        return value

    @field_validator("times")
    @classmethod
    def valid_times(cls, value):
        if any(not re.fullmatch(r"14:[0-5][0-9]", item) for item in value):
            raise ValueError("时间必须为14:00至14:59的HH:mm")
        if len(set(value)) != len(value):
            raise ValueError("提醒时间不能重复")
        return sorted(value)


class ScheduleUpdate(ScheduleCreate):
    version: Version


class ScheduleResponse(ScheduleCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    version: int
    timezone: Literal["Asia/Shanghai"] = "Asia/Shanghai"
    created_at: AwareDatetime
    updated_at: AwareDatetime


class ScheduleList(UTCResponse):
    items: list[ScheduleResponse]


class ScheduleSlotPreview(UTCResponse):
    local_time: str
    scheduled_at: AwareDatetime
    expires_at: AwareDatetime
    status: str
    reason: str
    run_id: str | None = None
    outbox_id: str | None = None


class SchedulePreview(UTCResponse):
    schedule_id: str
    checked_at: AwareDatetime
    timezone: Literal["Asia/Shanghai"] = "Asia/Shanghai"
    calendar: MarketCalendarStatus
    slots: list[ScheduleSlotPreview]


class ScheduleRunResponse(UTCResponse):
    id: str
    schedule_id: str
    schedule_name: str
    schedule_version: int
    exchange: CNExchange
    session_date: date
    local_time: str
    scheduled_at: AwareDatetime
    status: Literal["ENQUEUED", "MISSED"]
    reason: str
    rule_snapshot: dict[str, Any]
    calendar: MarketCalendarStatus
    outbox_id: str | None
    created_at: AwareDatetime


class ScheduleRunPage(UTCResponse):
    items: list[ScheduleRunResponse]
    total: int
    page: int
    page_size: int
