from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response

from cross_market.modules.portfolio.application import accounts, ledger, summary
from cross_market.modules.portfolio.application.schemas import (
    PortfolioAccount,
    PortfolioAccountCreate,
    PortfolioAccountList,
    PortfolioAccountUpdate,
    PortfolioEntry,
    PortfolioEntryCreate,
    PortfolioEntryPage,
    PortfolioReversalCreate,
    PortfolioSummary,
)
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


@router.get("/accounts", response_model=PortfolioAccountList)
async def list_accounts(session: Session):
    return await accounts.list_accounts(session)


@router.post("/accounts", response_model=PortfolioAccount, status_code=201)
async def create_account(body: PortfolioAccountCreate, session: Session):
    return await accounts.create_account(session, body)


@router.get("/accounts/{account_id}", response_model=PortfolioAccount)
async def get_account(account_id: EntityId, session: Session):
    return await accounts.get_account(session, account_id)


@router.put("/accounts/{account_id}", response_model=PortfolioAccount)
async def update_account(account_id: EntityId, body: PortfolioAccountUpdate, session: Session):
    return await accounts.update_account(session, account_id, body)


@router.delete("/accounts/{account_id}", status_code=204)
async def delete_account(account_id: EntityId, session: Session):
    await accounts.delete_account(session, account_id)
    return Response(status_code=204)


@router.get("/accounts/{account_id}/ledger", response_model=PortfolioEntryPage)
async def list_ledger(
    account_id: EntityId,
    session: Session,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    return await ledger.list_ledger(session, account_id, page, page_size)


@router.post("/accounts/{account_id}/entries", response_model=PortfolioEntry, status_code=201)
async def create_entry(account_id: EntityId, body: PortfolioEntryCreate, session: Session):
    return await ledger.create_entry(session, account_id, body)


@router.post(
    "/accounts/{account_id}/entries/{entry_id}/reverse",
    response_model=PortfolioEntry,
    status_code=201,
)
async def reverse_entry(
    account_id: EntityId, entry_id: EntityId, body: PortfolioReversalCreate, session: Session
):
    return await ledger.reverse_entry(session, account_id, entry_id, body)


@router.get("/accounts/{account_id}/summary", response_model=PortfolioSummary)
async def get_summary(account_id: EntityId, session: Session):
    return await summary.summary(session, account_id)
