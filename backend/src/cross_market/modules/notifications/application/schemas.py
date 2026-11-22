from typing import Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, field_validator

OutboxStatus = Literal["PENDING", "RETRY", "SENT", "DEAD"]


class NotificationMessage(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    event_id: str
    outbox_id: str
    title: str
    body: str
    payload: dict[str, Any]
    read_at: AwareDatetime | None
    created_at: AwareDatetime


class NotificationInboxPage(BaseModel):
    items: list[NotificationMessage]
    total: int
    page: int
    page_size: int
    unread_count: int


class NotificationOutbox(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    event_id: str
    channel: Literal["IN_APP"]
    title: str
    body: str
    status: OutboxStatus
    attempts: int
    max_attempts: int
    next_attempt_at: AwareDatetime
    created_at: AwareDatetime
    sent_at: AwareDatetime | None
    last_error: str | None


class NotificationOutboxPage(BaseModel):
    items: list[NotificationOutbox]
    total: int
    page: int
    page_size: int


class NotificationDelivery(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    outbox_id: str
    attempt: int
    status: Literal["SENT", "FAILED"]
    error_code: str | None
    created_at: AwareDatetime


class NotificationDeliveryList(BaseModel):
    items: list[NotificationDelivery]


class NotificationTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID


class NotificationReadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    read: Literal[True] = True

    @field_validator("read", mode="before")
    @classmethod
    def require_true(cls, value):
        if value is not True:
            raise ValueError("read 必须为 true")
        return value


class NotificationReadAllResult(BaseModel):
    updated: int
