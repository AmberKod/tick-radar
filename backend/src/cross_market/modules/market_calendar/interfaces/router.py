from datetime import UTC, datetime

from fastapi import APIRouter, Request

from cross_market.modules.market_calendar.application.schemas import (
    Exchange,
    MarketCalendarStatusesResponse,
)

router = APIRouter(tags=["market-calendar"])


@router.get("/api/v1/market-calendar/statuses", response_model=MarketCalendarStatusesResponse)
async def statuses(request: Request, exchange: Exchange | None = None):
    checked_at = datetime.now(UTC)
    service = request.app.state.market_calendar
    exchanges = [exchange] if exchange is not None else list(Exchange)
    return MarketCalendarStatusesResponse(
        statuses=[service.get_status(item, checked_at) for item in exchanges],
        checked_at=checked_at,
    )
