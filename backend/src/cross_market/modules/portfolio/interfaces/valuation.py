from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from cross_market.modules.portfolio.application.schemas import PortfolioSummary
from cross_market.modules.portfolio.application.valuation import value_summary
from cross_market.modules.portfolio.application.valuation_schemas import PortfolioValuationResponse
from cross_market.shared.database import get_session
from cross_market.shared.exceptions import BUSINESS_ERROR_RESPONSES
from cross_market.shared.identifiers import EntityId
from cross_market.shared.security import require_token

router = APIRouter(
    prefix="/api/v1/portfolio",
    tags=["portfolio"],
    dependencies=[Depends(require_token)],
    responses=BUSINESS_ERROR_RESPONSES,
)
Session = Annotated[Any, Depends(get_session, scope="function")]


@router.get("/accounts/{account_id}/valuation", response_model=PortfolioValuationResponse)
async def valuation(account_id: EntityId, request: Request, session: Session):
    from cross_market.modules.portfolio.application.summary import summary as get_summary

    summary = await get_summary(session, account_id)
    return await value_summary(
        PortfolioSummary.model_validate(summary), request.app.state.quote_service,
    )
