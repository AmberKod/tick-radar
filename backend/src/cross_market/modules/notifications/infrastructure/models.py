from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from cross_market.shared.database import Base


class UTCDateTime(TypeDecorator):
    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(
            DATETIME(fsp=6) if dialect.name == "mysql" else DateTime(timezone=True)
        )

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("时间必须包含时区")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def utcnow():
    return datetime.now(UTC)


def new_id():
    return str(uuid4())


class NotificationOutbox(Base):
    __tablename__ = "t_alert_outbox"
    __table_args__ = (Index("ix_alert_outbox_due", "status", "next_attempt_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_id: Mapped[str] = mapped_column(String(36), unique=True)
    channel: Mapped[str] = mapped_column(String(16), default="IN_APP")
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(String(2000))
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    next_attempt_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(160), nullable=True)


class NotificationDelivery(Base):
    __tablename__ = "t_alert_delivery"
    __table_args__ = (UniqueConstraint("outbox_id", "attempt", name="uq_alert_delivery_attempt"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    outbox_id: Mapped[str] = mapped_column(String(36), ForeignKey("t_alert_outbox.id"))
    attempt: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    error_code: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class InboxMessage(Base):
    __tablename__ = "t_notification_inbox"
    __table_args__ = (Index("ix_notification_inbox_created", "created_at", "id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    outbox_id: Mapped[str] = mapped_column(String(36), ForeignKey("t_alert_outbox.id"), unique=True)
    event_id: Mapped[str] = mapped_column(String(36), unique=True)
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(String(2000))
    payload: Mapped[dict] = mapped_column(JSON)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
