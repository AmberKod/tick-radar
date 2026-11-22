from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response

from cross_market.modules.watchlist.application import service
from cross_market.modules.watchlist.application.schemas import (
    GroupDTO,
    GroupInput,
    GroupOrder,
    GroupsDTO,
    ItemCreate,
    ItemDTO,
    ItemMove,
    ItemOrder,
    ItemsDTO,
    ItemUpdate,
)
from cross_market.shared.database import get_session
from cross_market.shared.exceptions import BUSINESS_ERROR_RESPONSES
from cross_market.shared.identifiers import EntityId
from cross_market.shared.security import require_token

router = APIRouter(
    prefix="/api/v1",
    tags=["watchlist"],
    dependencies=[Depends(require_token)],
    responses=BUSINESS_ERROR_RESPONSES,
)
Session = Annotated[Any, Depends(get_session, scope="function")]


@router.get("/watchlist-groups", response_model=GroupsDTO)
async def list_groups(session: Session):
    return await service.list_groups(session)


@router.post("/watchlist-groups", response_model=GroupDTO, status_code=201)
async def create_group(body: GroupInput, session: Session):
    return await service.create_group(session, body)


@router.put("/watchlist-groups/order", response_model=GroupsDTO)
async def order_groups(body: GroupOrder, session: Session):
    return await service.order_groups(session, body)


@router.put("/watchlist-groups/{group_id}", response_model=GroupDTO)
async def update_group(group_id: EntityId, body: GroupInput, session: Session):
    return await service.update_group(session, group_id, body)


@router.delete("/watchlist-groups/{group_id}", status_code=204)
async def delete_group(group_id: EntityId, session: Session):
    await service.delete_group(session, group_id)
    return Response(status_code=204)


@router.get("/watchlists", response_model=ItemsDTO)
async def list_items(group_id: EntityId, session: Session):
    return await service.list_items(session, group_id)


@router.post("/watchlists", response_model=ItemDTO, status_code=201)
async def create_item(body: ItemCreate, session: Session):
    return await service.create_item(session, body)


@router.put("/watchlists/order", response_model=ItemsDTO)
async def order_items(body: ItemOrder, session: Session):
    return await service.order_items(session, body)


@router.put("/watchlists/{item_id}", response_model=ItemDTO)
async def update_item(item_id: EntityId, body: ItemUpdate, session: Session):
    return await service.update_item(session, item_id, body)


@router.delete("/watchlists/{item_id}", status_code=204)
async def delete_item(item_id: EntityId, session: Session):
    await service.delete_item(session, item_id)
    return Response(status_code=204)


@router.post("/watchlists/{item_id}/move", response_model=ItemDTO)
async def move_item(item_id: EntityId, body: ItemMove, session: Session):
    return await service.move_item(session, item_id, body)
