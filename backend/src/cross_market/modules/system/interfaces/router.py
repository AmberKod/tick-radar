from datetime import UTC, datetime

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from cross_market.modules.system.application.registry import MODULES
from cross_market.modules.system.application.schemas import ModulesResponse, SystemStatus

router = APIRouter(tags=["system"])


class LiveStatus(BaseModel):
    status: str = "healthy"
    checked_at: datetime


@router.get("/health/live", response_model=LiveStatus)
async def live():
    return LiveStatus(checked_at=datetime.now(UTC))


@router.get("/health/ready", response_model=SystemStatus)
async def ready(request: Request, response: Response):
    result = await request.app.state.health_service.status()
    if result.components.mysql.status != "healthy":
        response.status_code = 503
    return result


@router.get("/health/system", response_model=SystemStatus)
@router.get("/api/v1/system/status", response_model=SystemStatus)
async def status(request: Request):
    return await request.app.state.health_service.status()


@router.get("/api/v1/system/modules", response_model=ModulesResponse)
async def modules():
    return ModulesResponse(modules=list(MODULES))
