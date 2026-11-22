from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response

from cross_market.modules.alerts.application import service
from cross_market.modules.alerts.application.schemas import (
    AlertEventPage,
    AlertPreviewResponse,
    AlertResetRequest,
    AlertRuleCreate,
    AlertRuleResponse,
    AlertRulesResponse,
    AlertRuleUpdate,
)
from cross_market.shared.database import get_session
from cross_market.shared.exceptions import BUSINESS_ERROR_RESPONSES
from cross_market.shared.identifiers import EntityId
from cross_market.shared.security import require_token

router = APIRouter(
    prefix="/api/v1/alerts",
    tags=["alerts"],
    dependencies=[Depends(require_token)],
    responses=BUSINESS_ERROR_RESPONSES,
)
Session = Annotated[Any, Depends(get_session, scope="function")]


@router.get("/rules", response_model=AlertRulesResponse)
async def list_rules(session: Session):
    return await service.list_rules(session)


@router.post("/rules", response_model=AlertRuleResponse, status_code=201)
async def create_rule(body: AlertRuleCreate, session: Session):
    return await service.create_rule(session, body)


@router.get("/rules/{rule_id}", response_model=AlertRuleResponse)
async def get_rule(rule_id: EntityId, session: Session):
    return await service.get_rule(session, rule_id)


@router.put("/rules/{rule_id}", response_model=AlertRuleResponse)
async def update_rule(rule_id: EntityId, body: AlertRuleUpdate, session: Session):
    return await service.update_rule(session, rule_id, body)


@router.delete("/rules/{rule_id}", status_code=204)
async def delete_rule(rule_id: EntityId, version: Annotated[int, Query(ge=1)], session: Session):
    await service.delete_rule(session, rule_id, version)
    return Response(status_code=204)


@router.post("/rules/{rule_id}/reset", response_model=AlertRuleResponse)
async def reset_rule(rule_id: EntityId, body: AlertResetRequest, session: Session):
    return await service.reset_rule(session, rule_id, body.version)


@router.post("/rules/{rule_id}/preview", response_model=AlertPreviewResponse)
async def preview_rule(rule_id: EntityId, request: Request, session: Session):
    return await service.preview_rule(session, rule_id, request.app.state.quote_service)


@router.get("/events", response_model=AlertEventPage)
async def list_events(
    session: Session,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    rule_id: EntityId | None = None,
):
    return await service.list_events(session, rule_id=rule_id, page=page, page_size=page_size)
