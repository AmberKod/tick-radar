from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response

from cross_market.modules.alerts.application import schedules as service
from cross_market.modules.alerts.application.schedule_schemas import (
    ScheduleCreate,
    ScheduleList,
    SchedulePreview,
    ScheduleResponse,
    ScheduleRunPage,
    ScheduleUpdate,
)
from cross_market.shared.database import get_session
from cross_market.shared.exceptions import BUSINESS_ERROR_RESPONSES
from cross_market.shared.identifiers import EntityId
from cross_market.shared.security import require_token

router = APIRouter(
    prefix="/api/v1/alerts",
    tags=["alert-schedules"],
    dependencies=[Depends(require_token)],
    responses=BUSINESS_ERROR_RESPONSES,
)
Session = Annotated[Any, Depends(get_session, scope="function")]


@router.get("/schedules", response_model=ScheduleList)
async def list_schedules(session: Session):
    return await service.list_schedules(session)


@router.post("/schedules", response_model=ScheduleResponse, status_code=201)
async def create_schedule(body: ScheduleCreate, session: Session):
    return await service.create_schedule(session, body)


@router.get("/schedules/{schedule_id}", response_model=ScheduleResponse)
async def get_schedule(schedule_id: EntityId, session: Session):
    return await service.get_schedule(session, schedule_id)


@router.put("/schedules/{schedule_id}", response_model=ScheduleResponse)
async def update_schedule(schedule_id: EntityId, body: ScheduleUpdate, session: Session):
    return await service.update_schedule(session, schedule_id, body)


@router.delete("/schedules/{schedule_id}", status_code=204)
async def delete_schedule(
    schedule_id: EntityId,
    version: Annotated[int, Query(ge=1)],
    session: Session,
):
    await service.delete_schedule(session, schedule_id, version)
    return Response(status_code=204)


@router.post("/schedules/{schedule_id}/preview", response_model=SchedulePreview)
async def preview_schedule(schedule_id: EntityId, request: Request, session: Session):
    return await service.preview_schedule(session, schedule_id, request.app.state.market_calendar)


@router.get("/schedule-runs", response_model=ScheduleRunPage)
async def list_runs(
    session: Session,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    schedule_id: EntityId | None = None,
):
    return await service.list_runs(session, schedule_id=schedule_id, page=page, page_size=page_size)
