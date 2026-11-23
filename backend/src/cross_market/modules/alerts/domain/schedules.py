from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

TIMEZONE = "Asia/Shanghai"
ZONE = ZoneInfo(TIMEZONE)


def aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("时间必须包含时区")
    return value.astimezone(UTC)


@dataclass(frozen=True)
class Calendar:
    session_date: date
    is_trading_day: bool | None
    state: str
    basis: str
    coverage_start: date
    coverage_end: date
    session_open: datetime | None = None
    session_close: datetime | None = None
    break_start: datetime | None = None
    break_end: datetime | None = None
    identity_valid: bool = True


@dataclass(frozen=True)
class Decision:
    status: str
    reason: str
    expires_at: datetime


def decide_slot(
    *, now: datetime, scheduled_at: datetime, active_since: datetime,
    grace_seconds: int, calendar: Calendar, enabled: bool, existing_status: str | None = None,
) -> Decision:
    now, due, active = map(aware_utc, (now, scheduled_at, active_since))
    expires = due + timedelta(seconds=grace_seconds)
    if calendar.session_close is not None:
        expires = min(expires, aware_utc(calendar.session_close))

    def result(status, reason):
        return Decision(status, reason, expires)

    if existing_status is not None:
        return result(existing_status, "该时点已有执行记录")
    if not enabled:
        return result("DISABLED", "提醒已停用")
    day = now.astimezone(ZONE).date()
    if (
        not calendar.identity_valid or calendar.session_date != day
        or due.astimezone(ZONE).date() != day
        or not calendar.coverage_start <= day <= calendar.coverage_end
        or calendar.is_trading_day is None or calendar.basis == "UNAVAILABLE"
        or calendar.state == "UNKNOWN"
    ):
        return result("SKIPPED", "日历不可用或日期不匹配，暂停判断")
    if not calendar.is_trading_day:
        return result("NON_TRADING", "当日为非交易日，不推算下一次提醒")
    opening, closing = calendar.session_open, calendar.session_close
    if opening is None or closing is None:
        return result("SKIPPED", "缺少当日常规交易时段")
    opening, closing = aware_utc(opening), aware_utc(closing)
    if (
        opening.astimezone(ZONE).date() != day or closing.astimezone(ZONE).date() != day
        or not opening <= due < closing
        or (calendar.break_start is None) != (calendar.break_end is None)
    ):
        return result("SKIPPED", "计划时刻不在有效常规交易时段")
    if calendar.break_start is not None and (
        aware_utc(calendar.break_start) <= due < aware_utc(calendar.break_end)
    ):
        return result("SKIPPED", "计划时刻处于午间休市")
    if now < due:
        return result("WAITING", "尚未到计划时刻")
    if active > due:
        return result("MISSED", "保存/启用晚于计划时刻，不追溯补发")
    if now >= expires:
        return result("MISSED", "已超过提醒窗口，不补发")
    if calendar.state != "REGULAR_SESSION":
        return result("SKIPPED", "当前不处于已确认的常规交易时段")
    return result("ENQUEUE", "交易日定时提醒窗口内")
