from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from cross_market.modules.notifications.application import service
from cross_market.modules.notifications.application.schemas import (
    NotificationDeliveryList,
    NotificationInboxPage,
    NotificationMessage,
    NotificationOutbox,
    NotificationOutboxPage,
    NotificationReadAllResult,
    NotificationReadRequest,
    NotificationTestRequest,
    OutboxStatus,
)
from cross_market.shared.database import get_session
from cross_market.shared.exceptions import BUSINESS_ERROR_RESPONSES
from cross_market.shared.identifiers import EntityId
from cross_market.shared.security import require_token

router = APIRouter(
    prefix="/api/v1/notifications",
    tags=["notifications"],
    dependencies=[Depends(require_token)],
    responses=BUSINESS_ERROR_RESPONSES,
)
Session = Annotated[Any, Depends(get_session, scope="function")]
Page = Annotated[int, Query(ge=1, le=1000000)]
PageSize = Annotated[int, Query(ge=1, le=100)]


@router.get("/inbox", response_model=NotificationInboxPage)
async def inbox(
    session: Session, page: Page = 1, page_size: PageSize = 20, unread_only: bool = False
):
    return await service.list_inbox(session, page, page_size, unread_only)


@router.put("/inbox/{message_id}/read", response_model=NotificationMessage)
async def mark_read(
    message_id: EntityId, session: Session, body: NotificationReadRequest | None = None
):
    return await service.mark_read(session, message_id)


@router.post("/inbox/read-all", response_model=NotificationReadAllResult)
async def read_all(session: Session):
    return await service.read_all(session)


@router.get("/outbox", response_model=NotificationOutboxPage)
async def outbox(
    session: Session, page: Page = 1, page_size: PageSize = 20, status: OutboxStatus | None = None
):
    return await service.list_outbox(session, page, page_size, status)


@router.get("/outbox/{outbox_id}/deliveries", response_model=NotificationDeliveryList)
async def deliveries(outbox_id: EntityId, session: Session):
    return await service.list_deliveries(session, outbox_id)


@router.post("/outbox/{outbox_id}/retry", response_model=NotificationOutbox)
async def retry(outbox_id: EntityId, session: Session):
    return await service.retry_outbox(session, outbox_id)


@router.post("/test", response_model=NotificationOutbox, status_code=201)
async def test_notification(body: NotificationTestRequest, session: Session):
    outbox_id = await service.enqueue(
        session,
        body.request_id,
        "站内通知测试",
        "这是一条投递测试，不代表行情触发。",
        {"kind": "DELIVERY_TEST"},
    )
    return await service.get_outbox(session, outbox_id)
