from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request

from cross_market.modules.securities.application import service
from cross_market.modules.securities.application.schemas import (
    SecurityCreate,
    SecurityDTO,
    SecurityFromQuote,
    SecurityPage,
    SecurityUpdate,
)
from cross_market.shared.database import get_session
from cross_market.shared.exceptions import BUSINESS_ERROR_RESPONSES
from cross_market.shared.identifiers import EntityId
from cross_market.shared.security import require_token

router = APIRouter(
    prefix="/api/v1/securities",
    tags=["securities"],
    dependencies=[Depends(require_token)],
    responses=BUSINESS_ERROR_RESPONSES,
)
Session = Annotated[Any, Depends(get_session, scope="function")]


@router.post("", response_model=SecurityDTO, status_code=201)
async def create_security(body: SecurityCreate, session: Session):
    return await service.create_security(session, body)


@router.get("", response_model=SecurityPage)
async def list_securities(
    session: Session,
    q: str = Query(default="", max_length=120),
    market: Literal["CN", "HK", "US"] | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    return await service.list_securities(
        session, q=q, market=market, page=page, page_size=page_size
    )


@router.post("/from-quote", response_model=SecurityDTO, status_code=201)
async def from_quote(request: Request, body: SecurityFromQuote, session: Session):
    return await service.create_from_quote(session, body, request.app.state.quote_service)


@router.get("/{security_id}", response_model=SecurityDTO)
async def detail(security_id: EntityId, session: Session):
    return await service.get_security(session, security_id)


@router.put("/{security_id}", response_model=SecurityDTO)
async def update_security(security_id: EntityId, body: SecurityUpdate, session: Session):
    return await service.update_security(session, security_id, body)
