from pydantic import BaseModel, ConfigDict, Field

from cross_market.modules.securities.application.schemas import SecurityDTO
from cross_market.shared.identifiers import EntityId


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class GroupInput(Input):
    name: str = Field(min_length=1, max_length=80)


class GroupDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: EntityId
    name: str
    position: int


class GroupsDTO(BaseModel):
    groups: list[GroupDTO]


class GroupOrder(Input):
    ids: list[EntityId] = Field(max_length=50)


class ItemOrder(Input):
    group_id: EntityId
    ids: list[EntityId] = Field(max_length=500)


class ItemUpdate(Input):
    note: str = Field(default="", max_length=500)


class ItemCreate(ItemUpdate):
    group_id: EntityId
    security_id: EntityId


class ItemMove(Input):
    group_id: EntityId
    position: int | None = Field(default=None, ge=0)


class ItemDTO(BaseModel):
    id: EntityId
    group_id: EntityId
    security_id: EntityId
    position: int
    note: str
    security: SecurityDTO


class ItemsDTO(BaseModel):
    items: list[ItemDTO]
