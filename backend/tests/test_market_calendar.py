import asyncio
import threading
from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi import FastAPI

from cross_market.modules.market_calendar.application.schemas import (
    CalendarBasis,
    CalendarState,
    Exchange,
)
from cross_market.modules.market_calendar.application.service import CalendarService
from cross_market.modules.market_calendar.infrastructure import calendars
from cross_market.modules.market_calendar.interfaces.router import router


def instant(value: str) -> datetime:
    return datetime.fromisoformat(value)


@pytest.fixture(scope="module")
def service():
    result = CalendarService()
    asyncio.run(result.warmup())
    return result


@pytest.mark.parametrize("exchange", list(Exchange))
def test_holiday_and_weekday(service, exchange):
    closed = service.get_status(exchange, instant("2026-01-01T12:00:00+00:00"))
    assert closed.state == CalendarState.CLOSED
    assert closed.is_trading_day is False
    trading = service.get_status(exchange, instant("2026-03-06T15:00:00+00:00"))
    assert trading.is_trading_day is True
    assert trading.coverage_start == date(2026, 1, 1)
    assert trading.coverage_end == date(2026, 12, 31)
    assert trading.calendar_version == "4.13.3"
    assert trading.scope == "REGULAR_EQUITIES_ONLY"


@pytest.mark.parametrize("exchange", [Exchange.SZSE, Exchange.BSE])
def test_reviewed_cn_shared_basis(service, exchange):
    now = instant("2026-03-06T02:00:00+00:00")
    status = service.get_status(exchange, now)
    shanghai = service.get_status(Exchange.SSE, now)
    assert status.calendar_name == "XSHG"
    assert status.basis == CalendarBasis.CN_2026_REVIEWED_SHARED
    assert "已核对" in status.reason and "2026" in status.reason
    assert status.session_open == shanghai.session_open
    assert shanghai.basis == CalendarBasis.EXCHANGE_CALENDARS_REGULAR


@pytest.mark.parametrize("exchange", [Exchange.SSE, Exchange.SZSE, Exchange.BSE])
@pytest.mark.parametrize(
    ("clock", "state", "next_clock"),
    [
        ("09:29:59", "OUTSIDE_REGULAR_SESSION", "09:30:00"),
        ("09:30:00", "REGULAR_SESSION", "13:00:00"),
        ("11:29:59", "REGULAR_SESSION", "13:00:00"),
        ("11:30:00", "LUNCH_BREAK", "13:00:00"),
        ("12:00:00", "LUNCH_BREAK", "13:00:00"),
        ("13:00:00", "REGULAR_SESSION", "09:30:00"),
        ("14:59:59", "REGULAR_SESSION", "09:30:00"),
        ("15:00:00", "OUTSIDE_REGULAR_SESSION", "09:30:00"),
    ],
)
def test_cn_boundaries(service, exchange, clock, state, next_clock):
    now = instant(f"2026-03-06T{clock}+08:00")
    status = service.get_status(exchange, now)
    assert status.state == state
    assert status.next_open.strftime("%H:%M:%S") == next_clock
    assert status.next_open > now
    assert status.next_close > now
    if clock < "15:00:00":
        assert status.next_close == status.session_close
    else:
        assert status.next_close.date() == date(2026, 3, 9)


def test_hk_half_day(service):
    status = service.get_status(Exchange.HKEX, instant("2026-12-24T11:59:59+08:00"))
    assert status.state == CalendarState.REGULAR_SESSION
    assert status.is_early_close is True
    assert status.session_close.hour == 12
    assert status.break_start is None and status.break_end is None
    closed = service.get_status(Exchange.HKEX, instant("2026-12-24T12:00:00+08:00"))
    assert closed.state == CalendarState.OUTSIDE_REGULAR_SESSION
    assert closed.next_close > closed.checked_at


def test_hk_lunch(service):
    status = service.get_status(Exchange.HKEX, instant("2026-03-06T12:00:00+08:00"))
    assert status.state == CalendarState.LUNCH_BREAK
    assert status.next_open == instant("2026-03-06T13:00:00+08:00")
    assert status.next_close == instant("2026-03-06T16:00:00+08:00")


@pytest.mark.parametrize("exchange", [Exchange.NYSE, Exchange.NASDAQ, Exchange.AMEX])
def test_us_early_close(service, exchange):
    status = service.get_status(exchange, instant("2026-11-27T12:59:59-05:00"))
    assert status.state == CalendarState.REGULAR_SESSION
    assert status.is_early_close is True
    assert status.session_close == instant("2026-11-27T13:00:00-05:00")
    assert status.break_start is None and status.break_end is None
    assert service.get_status(exchange, status.session_close).state == (
        CalendarState.OUTSIDE_REGULAR_SESSION
    )
    if exchange != Exchange.NYSE:
        assert any("共享NYSE" in item for item in status.warnings)
    assert any("竞价" in item and "个股停牌" in item for item in status.warnings)


@pytest.mark.parametrize(
    ("day", "utc_open"), [("2026-03-06", "14:30:00"), ("2026-03-09", "13:30:00")]
)
def test_dst(service, day, utc_open):
    expected = instant(f"{day}T{utc_open}+00:00")
    status = service.get_status(Exchange.NYSE, expected)
    assert status.session_open == expected
    assert status.state == CalendarState.REGULAR_SESSION
    assert status.session_open.astimezone(ZoneInfo("America/New_York")).hour == 9


def test_new_york_uses_local_date(service):
    status = service.get_status(Exchange.NYSE, instant("2026-03-07T01:00:00+00:00"))
    assert status.session_date == date(2026, 3, 6)
    assert status.is_trading_day is True
    assert status.state == CalendarState.OUTSIDE_REGULAR_SESSION
    # UTC进入2027时，纽约仍在已验证的2026年。
    status = service.get_status(Exchange.NYSE, instant("2027-01-01T01:00:00+00:00"))
    assert status.session_date == date(2026, 12, 31)
    assert status.state != CalendarState.UNKNOWN


@pytest.mark.parametrize("day", ["2027-01-01", "2027-01-02", "2025-12-31"])
@pytest.mark.parametrize("exchange", list(Exchange))
def test_out_of_range_even_on_weekends(service, day, exchange):
    status = service.get_status(exchange, instant(f"{day}T12:00:00+00:00"))
    assert status.state == CalendarState.UNKNOWN
    assert status.basis == CalendarBasis.UNAVAILABLE
    assert status.is_trading_day is None and status.is_early_close is None
    assert status.next_open is None and status.next_close is None


@pytest.mark.parametrize("exchange", list(Exchange))
def test_yearend_no_projection(service, exchange):
    zone = ZoneInfo(
        "America/New_York"
        if exchange in (Exchange.NYSE, Exchange.NASDAQ, Exchange.AMEX)
        else "Asia/Shanghai"
    )
    now = datetime(2026, 12, 31, 23, tzinfo=zone)
    status = service.get_status(exchange, now)
    assert status.session_date == date(2026, 12, 31)
    assert status.state == CalendarState.OUTSIDE_REGULAR_SESSION
    assert status.next_open is None and status.next_close is None
    assert any("2027" in warning for warning in status.warnings)


def test_naive_rejected(service):
    with pytest.raises(ValueError, match="时区"):
        service.get_status(Exchange.SSE, datetime(2026, 3, 6))


async def test_load_failure_fail_closed():
    result = CalendarService()
    with patch.object(calendars, "load_calendar", side_effect=RuntimeError("模拟失败")):
        await result.warmup()
    for exchange in Exchange:
        status = result.get_status(exchange, instant("2026-03-06T10:00:00+08:00"))
        assert status.state == CalendarState.UNKNOWN
        assert status.basis == CalendarBasis.UNAVAILABLE
        assert status.next_open is None and status.next_close is None
        assert "加载失败" in status.reason


async def test_warmup_threaded_once_and_query_cached():
    result = CalendarService()
    calls = []
    original = calendars.load_calendar
    main_thread = threading.get_ident()

    def tracked(name):
        calls.append((name, threading.get_ident()))
        return original(name)

    with patch.object(calendars, "load_calendar", side_effect=tracked):
        await asyncio.gather(result.warmup(), result.warmup())
    assert sorted(name for name, _ in calls) == ["XHKG", "XNYS", "XSHG"]
    assert all(thread_id != main_thread for _, thread_id in calls)
    with patch.object(calendars, "load_calendar", side_effect=AssertionError("不应重建")):
        for _ in range(100):
            assert result.get_status("SSE", instant("2026-03-06T02:00:00+00:00")).state == (
                CalendarState.REGULAR_SESSION
            )


async def test_manual_close_and_future_skip():
    result = CalendarService({"SSE:2026-03-09": "临时休市：测试", "SSE:2026-03-10": "继续休市"})
    await result.warmup()
    before = result.get_status("SSE", instant("2026-03-06T15:00:00+08:00"))
    assert before.next_open == instant("2026-03-11T09:30:00+08:00")
    assert before.next_close == instant("2026-03-11T15:00:00+08:00")
    closed = result.get_status("SSE", instant("2026-03-09T10:00:00+08:00"))
    assert closed.state == CalendarState.CLOSED
    assert closed.basis == CalendarBasis.MANUAL_CLOSED
    assert closed.reason == "临时休市：测试"
    assert closed.is_trading_day is False
    assert closed.session_open is None and closed.session_close is None
    assert closed.next_open == before.next_open
    unaffected = result.get_status("SZSE", instant("2026-03-09T10:00:00+08:00"))
    assert unaffected.state == CalendarState.REGULAR_SESSION


async def test_manual_close_even_when_calendar_unavailable():
    result = CalendarService({"SSE:2026-03-06": "临时休市"})
    with patch.object(calendars, "load_calendar", side_effect=RuntimeError("模拟失败")):
        await result.warmup()
    status = result.get_status("SSE", instant("2026-03-06T10:00:00+08:00"))
    assert status.basis == CalendarBasis.MANUAL_CLOSED
    assert status.state == CalendarState.CLOSED
    assert status.reason == "临时休市"
    assert status.next_open is None and status.next_close is None


@pytest.mark.parametrize(
    "config",
    [
        [],
        {"UNKNOWN:2026-03-06": "原因"},
        {"BSE:2026-02-30": "原因"},
        {"SSE:20260306": "原因"},
        {"SSE:2027-01-01": "原因"},
        {"SSE:2026-03-06": " "},
        {"SSE:2026-03-06": None},
        {1: "原因"},
        {f"SSE:2026-{index}": "原因" for index in range(101)},
    ],
)
def test_invalid_override(config):
    with pytest.raises(ValueError):
        CalendarService(config)


async def test_partial_failure_isolated():
    original = calendars.load_calendar

    def fail_cn(name):
        if name == "XSHG":
            raise RuntimeError("模拟失败")
        return original(name)

    result = CalendarService()
    with patch.object(calendars, "load_calendar", side_effect=fail_cn):
        await result.warmup()
    now = instant("2026-03-06T15:00:00+00:00")
    assert result.get_status("SSE", now).state == CalendarState.UNKNOWN
    assert result.get_status("NYSE", now).state == CalendarState.REGULAR_SESSION


async def test_router_contract(service):
    app = FastAPI()
    app.state.market_calendar = service
    app.include_router(router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/market-calendar/statuses")
        assert response.status_code == 200
        body = response.json()
        assert [row["exchange"] for row in body["statuses"]] == [item.value for item in Exchange]
        assert all(row["checked_at"] == body["checked_at"] for row in body["statuses"])
        assert instant(body["checked_at"]).utcoffset().total_seconds() == 0
        single = await client.get("/api/v1/market-calendar/statuses", params={"exchange": "BSE"})
        assert [row["exchange"] for row in single.json()["statuses"]] == ["BSE"]
        invalid = await client.get("/api/v1/market-calendar/statuses", params={"exchange": "XBOM"})
        assert invalid.status_code == 422
    parameters = app.openapi()["paths"]["/api/v1/market-calendar/statuses"]["get"]["parameters"]
    assert [parameter["name"] for parameter in parameters] == ["exchange"]


@pytest.mark.parametrize(
    "clock,state,quality",
    [
        ("2026-03-06T10:00:00+08:00", "REGULAR_SESSION", "UNKNOWN"),
        ("2026-03-06T12:00:00+08:00", "LUNCH_BREAK", "UNKNOWN"),
        ("2026-03-06T15:00:00+08:00", "OUTSIDE_REGULAR_SESSION", "UNKNOWN"),
        ("2026-03-07T10:00:00+08:00", "CLOSED", "MARKET_CLOSED"),
        ("2027-01-02T10:00:00+08:00", "UNKNOWN", "UNKNOWN"),
    ],
)
def test_quote_quality_and_calendar_state_remain_independent(service, clock, state, quality):
    from cross_market.modules.market_data.application.schemas import QuoteDTO
    from cross_market.modules.market_data.application.service import QuoteService

    checked_at = instant(clock)
    quote = QuoteDTO(
        symbol="CN:000001",
        market="CN",
        currency="CNY",
        provider_symbol="sz000001",
        price="10.01",
        received_at=checked_at,
        quality_status="UNKNOWN",
    )
    source = QuoteService(None, None, None, calendar=service)
    result = source.present(quote, checked_at)
    assert result.market_state == state
    assert result.quality_status == quality
    assert result.delay_status == "UNKNOWN"
    assert result.price == quote.price
    assert quote.market_state == "UNKNOWN"
    assert result.market_state_basis == (
        "UNAVAILABLE" if state == "UNKNOWN" else "CN_2026_REVIEWED_SHARED"
    )


def test_stale_quote_is_not_freshened_by_trading_session(service):
    from datetime import timedelta

    from cross_market.modules.market_data.application.schemas import QuoteDTO
    from cross_market.modules.market_data.application.service import QuoteService

    checked_at = instant("2026-03-06T10:00:00+08:00")
    quote = QuoteDTO(
        symbol="CN:600519",
        market="CN",
        currency="CNY",
        provider_symbol="sh600519",
        price="10",
        received_at=checked_at - timedelta(seconds=181),
    )
    result = QuoteService(None, None, None, calendar=service).present(quote, checked_at)
    assert result.market_state == "REGULAR_SESSION"
    assert result.quality_status == "STALE"
    assert result.received_at == quote.received_at
    assert result.delay_status == "UNKNOWN"


def test_missing_exchange_or_calendar_does_not_reuse_cached_state(service):
    from cross_market.modules.market_data.application.schemas import QuoteDTO
    from cross_market.modules.market_data.application.service import QuoteService

    now = instant("2026-03-06T15:00:00+00:00")
    quote = QuoteDTO(
        symbol="US:AAPL",
        market="US",
        currency="USD",
        provider_symbol="usAAPL",
        market_state="REGULAR_SESSION",
        market_state_reason="旧缓存状态",
    )
    for calendar in (None, service):
        result = QuoteService(None, None, None, calendar=calendar).present(quote, now)
        assert result.market_state == "UNKNOWN"
        assert result.market_state_reason != "旧缓存状态"
    quote.provider_exchange = "NASDAQ"
    result = QuoteService(None, None, None, calendar=service).present(quote, now)
    assert result.market_state == "REGULAR_SESSION"


@pytest.mark.parametrize("exchange", list(Exchange))
def test_reviewed_2026_full_year_holidays_and_weekends(service, exchange):
    from datetime import timedelta

    # 2026年度交易所公告核对表；仅覆盖常规股票，不推算次年。
    holidays = {
        "CN": "01-01 01-02 02-16 02-17 02-18 02-19 02-20 02-23 04-06 "
        "05-01 05-04 05-05 06-19 09-25 10-01 10-02 10-05 10-06 10-07",
        "HK": "01-01 02-17 02-18 02-19 04-03 04-06 04-07 05-01 05-25 06-19 07-01 10-01 10-19 12-25",
        "US": "01-01 01-19 02-16 04-03 05-25 06-19 07-03 09-07 11-26 12-25",
    }
    sample = service.get_status(exchange, instant("2026-06-01T12:00:00+00:00"))
    closed_days = {date.fromisoformat("2026-" + item) for item in holidays[sample.market].split()}
    day = date(2026, 1, 1)
    while day.year == 2026:
        now = datetime.combine(day, datetime.min.time(), ZoneInfo(sample.timezone))
        status = service.get_status(exchange, now)
        assert status.is_trading_day is (day.weekday() < 5 and day not in closed_days), day
        assert status.state != CalendarState.UNKNOWN
        day += timedelta(days=1)
