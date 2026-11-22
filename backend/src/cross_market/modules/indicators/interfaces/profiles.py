from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response

from cross_market.modules.indicators.application import profiles
from cross_market.modules.indicators.application.profile_schemas import (
    ProfileInput,
    ProfileResponse,
    ProfilesResponse,
    ProfileUpdate,
)
from cross_market.shared.database import get_session
from cross_market.shared.exceptions import BUSINESS_ERROR_RESPONSES
from cross_market.shared.identifiers import EntityId
from cross_market.shared.security import require_token

router = APIRouter(
    prefix="/api/v1/indicators/profiles",
    tags=["indicator-profiles"],
    dependencies=[Depends(require_token)],
    responses=BUSINESS_ERROR_RESPONSES,
)
Session = Annotated[Any, Depends(get_session, scope="function")]


@router.get("", response_model=ProfilesResponse)
async def list_profiles(session: Session):
    return await profiles.list_profiles(session)


@router.post("", response_model=ProfileResponse, status_code=201)
async def create_profile(body: ProfileInput, session: Session):
    return await profiles.create_profile(session, body)


@router.get("/{profile_id}", response_model=ProfileResponse)
async def get_profile(profile_id: EntityId, session: Session):
    return await profiles.get_profile(session, profile_id)


@router.put("/{profile_id}", response_model=ProfileResponse)
async def update_profile(profile_id: EntityId, body: ProfileUpdate, session: Session):
    return await profiles.update_profile(session, profile_id, body)


@router.delete("/{profile_id}", status_code=204)
async def delete_profile(
    profile_id: EntityId, version: Annotated[int, Query(ge=1)], session: Session
):
    await profiles.delete_profile(session, profile_id, version)
    return Response(status_code=204)
