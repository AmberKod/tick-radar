from fastapi import APIRouter, Depends, Query, Request

from cross_market.modules.market_data.application.schemas import (
    QuoteDTO,
    QuotesResponse,
    RefreshRequest,
)
from cross_market.shared.exceptions import AppError
from cross_market.shared.security import require_token

router = APIRouter(prefix="/api/v1/market", tags=["market"])


async def lookup(request: Request, symbols: list[str], refresh: bool):
    if refresh and request.method == "GET":
        raise AppError(422, "REFRESH_REQUIRES_POST", "强制刷新请使用鉴权POST接口")
    try:
        return await request.app.state.quote_service.get_quotes(symbols, refresh=refresh)
    except ValueError as exc:
        raise AppError(422, "INVALID_SYMBOLS", "证券代码或数量无效") from exc


@router.get("/quote", response_model=QuoteDTO)
async def quote(request: Request, symbol: str = Query(max_length=40), refresh: bool = False):
    response = await lookup(request, [symbol], refresh)
    return response.quotes[0]


@router.get("/quotes", response_model=QuotesResponse)
async def quotes(request: Request, symbols: str = Query(max_length=2049), refresh: bool = False):
    return await lookup(request, symbols.split(","), refresh)


@router.post("/refresh", response_model=QuotesResponse, dependencies=[Depends(require_token)])
async def refresh_quotes(request: Request, body: RefreshRequest):
    return await lookup(request, body.symbols, True)
