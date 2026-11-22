from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field


class Exchange(StrEnum):
    SSE = "SSE"
    SZSE = "SZSE"
    BSE = "BSE"
    HKEX = "HKEX"
    NYSE = "NYSE"
    NASDAQ = "NASDAQ"
    AMEX = "AMEX"


class Market(StrEnum):
    CN = "CN"
    HK = "HK"
    US = "US"


class CalendarState(StrEnum):
    REGULAR_SESSION = "REGULAR_SESSION"
    LUNCH_BREAK = "LUNCH_BREAK"
    OUTSIDE_REGULAR_SESSION = "OUTSIDE_REGULAR_SESSION"
    CLOSED = "CLOSED"
    UNKNOWN = "UNKNOWN"


class CalendarBasis(StrEnum):
    EXCHANGE_CALENDARS_REGULAR = "EXCHANGE_CALENDARS_REGULAR"
    CN_2026_REVIEWED_SHARED = "CN_2026_REVIEWED_SHARED"
    MANUAL_CLOSED = "MANUAL_CLOSED"
    UNAVAILABLE = "UNAVAILABLE"


class MarketCalendarStatus(BaseModel):
    exchange: Exchange
    market: Market
    state: CalendarState
    timezone: str
    local_time: AwareDatetime
    checked_at: AwareDatetime
    session_date: date
    is_trading_day: bool | None = None
    is_early_close: bool | None = None
    session_open: AwareDatetime | None = None
    break_start: AwareDatetime | None = None
    break_end: AwareDatetime | None = None
    session_close: AwareDatetime | None = None
    next_open: AwareDatetime | None = None
    next_close: AwareDatetime | None = None
    calendar_name: str
    calendar_version: str
    coverage_start: date
    coverage_end: date
    basis: CalendarBasis
    reason: str
    warnings: list[str] = Field(default_factory=list)
    scope: Literal["REGULAR_EQUITIES_ONLY"] = "REGULAR_EQUITIES_ONLY"


class MarketCalendarStatusesResponse(BaseModel):
    statuses: list[MarketCalendarStatus]
    checked_at: AwareDatetime
