from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from importlib.metadata import version
from types import MappingProxyType

import exchange_calendars
import pandas as pd

COVERAGE_START = date(2026, 1, 1)
COVERAGE_END = date(2026, 12, 31)
CALENDAR_VERSION = version("exchange-calendars")
CN_REVIEW_SOURCES = (
    "https://www.sse.com.cn/disclosure/announcement/general/c/c_20251222_10802507.shtml",
    "https://www.szse.cn/disclosure/notice/t20251222_618087.html",
    "https://www.bse.cn/important_news/200027428.html",
)


@dataclass(frozen=True)
class Session:
    session_date: date
    open: datetime
    break_start: datetime | None
    break_end: datetime | None
    close: datetime


@dataclass(frozen=True)
class CalendarRows:
    sessions: Mapping[date, Session]
    opens: tuple[datetime, ...]
    closes: tuple[datetime, ...]


def load_calendar(name: str) -> CalendarRows:
    calendar = exchange_calendars.get_calendar(
        name, start=COVERAGE_START.isoformat(), end=COVERAGE_END.isoformat()
    )
    sessions = {}
    opens = []
    closes = []
    for label, row in calendar.schedule.iterrows():
        session_date = label.date()
        if not COVERAGE_START <= session_date <= COVERAGE_END:
            continue
        session = Session(
            session_date=session_date,
            open=row["open"].to_pydatetime(),
            break_start=None if pd.isna(row["break_start"]) else row["break_start"].to_pydatetime(),
            break_end=None if pd.isna(row["break_end"]) else row["break_end"].to_pydatetime(),
            close=row["close"].to_pydatetime(),
        )
        sessions[session_date] = session
        opens.append(session.open)
        if session.break_end is not None:
            opens.append(session.break_end)
        closes.append(session.close)
    if not sessions:
        raise ValueError(f"{name} 的2026日历为空")
    return CalendarRows(MappingProxyType(sessions), tuple(sorted(opens)), tuple(sorted(closes)))
