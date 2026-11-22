import asyncio
import logging
from bisect import bisect_right
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from cross_market.modules.market_calendar.application.schemas import (
    CalendarBasis,
    CalendarState,
    Exchange,
    Market,
    MarketCalendarStatus,
)
from cross_market.modules.market_calendar.infrastructure import calendars

logger = logging.getLogger(__name__)

# 显式映射，BSE 不使用库中指向孟买交易所的同名别名。
EXCHANGE_CONFIG = {
    Exchange.SSE: ("XSHG", Market.CN, "Asia/Shanghai", time(15, 0)),
    Exchange.SZSE: ("XSHG", Market.CN, "Asia/Shanghai", time(15, 0)),
    Exchange.BSE: ("XSHG", Market.CN, "Asia/Shanghai", time(15, 0)),
    Exchange.HKEX: ("XHKG", Market.HK, "Asia/Hong_Kong", time(16, 0)),
    Exchange.NYSE: ("XNYS", Market.US, "America/New_York", time(16, 0)),
    Exchange.NASDAQ: ("XNYS", Market.US, "America/New_York", time(16, 0)),
    Exchange.AMEX: ("XNYS", Market.US, "America/New_York", time(16, 0)),
}


class CalendarService:
    def __init__(self, closed_dates: dict[str, str] | None = None):
        if closed_dates is not None and not isinstance(closed_dates, dict):
            raise ValueError("临时闭市配置必须为字典")
        if closed_dates is not None and len(closed_dates) > 100:
            raise ValueError("临时闭市配置最多100项")
        self._closed_dates: dict[tuple[Exchange, date], str] = {}
        for key, reason in (closed_dates or {}).items():
            if not isinstance(key, str) or not isinstance(reason, str) or not reason.strip():
                raise ValueError("临时闭市键和原因必须为非空字符串")
            try:
                exchange_text, day_text = key.split(":")
                exchange = Exchange(exchange_text)
                day = date.fromisoformat(day_text)
                if day.isoformat() != day_text:
                    raise ValueError("日期格式必须为YYYY-MM-DD")
                if not calendars.COVERAGE_START <= day <= calendars.COVERAGE_END:
                    raise ValueError("临时闭市日期超出2026验证范围")
            except ValueError as exc:
                raise ValueError(f"无效临时闭市键：{key}") from exc
            self._closed_dates[exchange, day] = reason
        self._rows: dict[Exchange, calendars.CalendarRows] = {}
        self._failures: dict[str, str] = {}
        self._warmed = False
        self._warmup_lock = asyncio.Lock()

    async def warmup(self) -> None:
        async with self._warmup_lock:
            if self._warmed:
                return
            results = await asyncio.gather(
                *(asyncio.to_thread(self._prepare, name) for name in ("XSHG", "XHKG", "XNYS")),
                return_exceptions=True,
            )
            for name, result in zip(("XSHG", "XHKG", "XNYS"), results, strict=True):
                if isinstance(result, BaseException):
                    self._failures[name] = type(result).__name__
                    logger.error(
                        "",
                        extra={
                            "event": "calendar_load_failed",
                            "exception_type": type(result).__name__,
                        },
                    )
                else:
                    self._rows.update(result)
            self._warmed = True

    def _prepare(self, name: str) -> dict[Exchange, calendars.CalendarRows]:
        rows = calendars.load_calendar(name)
        prepared = {}
        for exchange, config in EXCHANGE_CONFIG.items():
            if config[0] != name:
                continue
            sessions = {
                day: row
                for day, row in rows.sessions.items()
                if (exchange, day) not in self._closed_dates
            }
            opens = sorted(
                point
                for row in sessions.values()
                for point in (row.open, row.break_end)
                if point is not None
            )
            closes = sorted(row.close for row in sessions.values())
            prepared[exchange] = calendars.CalendarRows(sessions, tuple(opens), tuple(closes))
        return prepared

    def get_status(self, exchange: Exchange | str, now: datetime) -> MarketCalendarStatus:
        exchange = Exchange(exchange)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now必须为带时区的datetime")
        checked_at = now.astimezone(UTC)
        name, market, timezone, normal_close = EXCHANGE_CONFIG[exchange]
        local_time = checked_at.astimezone(ZoneInfo(timezone))
        day = local_time.date()
        warnings = ["仅覆盖常规股票交易；扩展时段、竞价及个股停牌未覆盖。"]
        basis = CalendarBasis.EXCHANGE_CALENDARS_REGULAR
        shared_reason = ""
        if exchange in (Exchange.SZSE, Exchange.BSE):
            basis = CalendarBasis.CN_2026_REVIEWED_SHARED
            shared_reason = "已核对沪深北2026年休市公告同日，显式共享XSHG常规日历。"
        if exchange in (Exchange.NASDAQ, Exchange.AMEX):
            warnings.append("共享NYSE（XNYS）常规日历，不代表本交易所所有产品或特殊安排。")
        status = MarketCalendarStatus(
            exchange=exchange,
            market=market,
            state=CalendarState.UNKNOWN,
            timezone=timezone,
            local_time=local_time,
            checked_at=checked_at,
            session_date=day,
            calendar_name=name,
            calendar_version=calendars.CALENDAR_VERSION,
            coverage_start=calendars.COVERAGE_START,
            coverage_end=calendars.COVERAGE_END,
            basis=CalendarBasis.UNAVAILABLE,
            reason="",
            warnings=warnings,
        )
        if not calendars.COVERAGE_START <= day <= calendars.COVERAGE_END:
            status.reason = "本地日期超出2026年已验证覆盖范围，无法判断交易状态。"
            status.warnings.append("未验证覆盖范围内不推算交易日及下一次开收盘。")
            return status
        rows = self._rows.get(exchange)
        manual_reason = self._closed_dates.get((exchange, day))
        if rows is None and manual_reason is None:
            status.reason = (
                "日历加载失败，无法判断交易状态。"
                if name in self._failures
                else ("日历尚未完成预热，无法判断交易状态。")
            )
            return status
        status.basis = basis
        if rows is not None:
            open_index = bisect_right(rows.opens, checked_at)
            close_index = bisect_right(rows.closes, checked_at)
            if open_index < len(rows.opens):
                status.next_open = rows.opens[open_index].astimezone(ZoneInfo(timezone))
            if close_index < len(rows.closes):
                status.next_close = rows.closes[close_index].astimezone(ZoneInfo(timezone))
            if status.next_open is None or status.next_close is None:
                status.warnings.append("2026年已验证覆盖内无后续开盘或收盘，不推算2027年。")
        else:
            status.warnings.append("日历不可用，无法确定下一次开收盘。")
        if manual_reason is not None:
            status.state = CalendarState.CLOSED
            status.is_trading_day = False
            status.is_early_close = False
            status.basis = CalendarBasis.MANUAL_CLOSED
            status.reason = manual_reason
            return status
        row = rows.sessions.get(day)
        status.is_trading_day = row is not None
        status.is_early_close = False
        if row is None:
            status.state = CalendarState.CLOSED
            status.reason = shared_reason + "当日为非交易日。"
            return status
        zone = ZoneInfo(timezone)
        status.session_open = row.open.astimezone(zone)
        status.session_close = row.close.astimezone(zone)
        status.break_start = row.break_start.astimezone(zone) if row.break_start else None
        status.break_end = row.break_end.astimezone(zone) if row.break_end else None
        status.is_early_close = status.session_close.time() < normal_close
        if row.open <= checked_at < row.close:
            if row.break_start is not None and row.break_start <= checked_at < row.break_end:
                status.state = CalendarState.LUNCH_BREAK
                status.reason = shared_reason + "常规交易午间休市。"
            else:
                status.state = CalendarState.REGULAR_SESSION
                status.reason = shared_reason + "处于常规股票交易时段。"
        else:
            status.state = CalendarState.OUTSIDE_REGULAR_SESSION
            status.reason = shared_reason + "当日为交易日，当前在常规交易时段之外。"
        return status
