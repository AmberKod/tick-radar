from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from cross_market.modules.portfolio.application import transfers
from cross_market.modules.portfolio.application.schemas import PortfolioReversalCreate
from cross_market.modules.portfolio.application.transfer_schemas import (
    PortfolioTransfer,
    PortfolioTransferCreate,
    PortfolioTransferPage,
)
from cross_market.shared.database import get_session
from cross_market.shared.exceptions import BUSINESS_ERROR_RESPONSES
from cross_market.shared.identifiers import EntityId
from cross_market.shared.security import require_token

router = APIRouter(
    prefix="/api/v1/portfolio/transfers",
    tags=["portfolio"],
    dependencies=[Depends(require_token)],
    responses=BUSINESS_ERROR_RESPONSES,
)
Session = Annotated[Any, Depends(get_session, scope="function")]


@router.post("", response_model=PortfolioTransfer, status_code=201)
async def create_transfer(body: PortfolioTransferCreate, session: Session):
    return await transfers.create_transfer(session, body)


@router.get("", response_model=PortfolioTransferPage)
async def list_transfers(
    session: Session,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    account_id: EntityId | None = None,
):
    return await transfers.list_transfers(session, page, page_size, account_id)


@router.get("/{transfer_id}", response_model=PortfolioTransfer)
async def get_transfer(transfer_id: EntityId, session: Session):
    return await transfers.get_transfer(session, transfer_id)


@router.post("/{transfer_id}/reverse", response_model=PortfolioTransfer)
async def reverse_transfer(transfer_id: EntityId, body: PortfolioReversalCreate, session: Session):
    return await transfers.reverse_transfer(session, transfer_id, body)
