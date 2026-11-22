from fastapi import APIRouter, Request

from cross_market.modules.indicators.application.schemas import (
    DailyIndicatorsResponse,
    IndicatorRequest,
)
from cross_market.shared.exceptions import BUSINESS_ERROR_RESPONSES, AppError

router = APIRouter(
    prefix="/api/v1/indicators", tags=["indicators"], responses=BUSINESS_ERROR_RESPONSES
)


@router.post("/daily", response_model=DailyIndicatorsResponse)
async def daily_indicators(request: Request, body: IndicatorRequest):
    try:
        return await request.app.state.indicator_service.calculate_daily(body)
    except ValueError as exc:
        raise AppError(422, "INVALID_INDICATOR_REQUEST", "日线指标请求参数无效") from exc
