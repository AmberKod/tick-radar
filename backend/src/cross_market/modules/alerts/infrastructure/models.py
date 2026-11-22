from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from cross_market.shared.database import Base

TIMESTAMP = DateTime(timezone=True).with_variant(DATETIME(fsp=6), "mysql")


def new_id():
    return str(uuid4())


def utcnow():
    return datetime.now(UTC)


class AlertRule(Base):
    __tablename__ = "t_alert_rule"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(80))
    security_id: Mapped[str] = mapped_column(ForeignKey("t_security.id"), index=True)
    rule_type: Mapped[str] = mapped_column(String(24))
    mode: Mapped[str] = mapped_column(String(16))
    threshold: Mapped[str] = mapped_column(String(34))
    reset_threshold: Mapped[str] = mapped_column(String(34))
    cooldown_seconds: Mapped[int] = mapped_column(Integer, default=300)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=utcnow)


class AlertRuleState(Base):
    __tablename__ = "t_alert_rule_state"

    rule_id: Mapped[str] = mapped_column(ForeignKey("t_alert_rule.id"), primary_key=True)
    phase: Mapped[str] = mapped_column(String(16))
    last_value: Mapped[str | None] = mapped_column(String(128))
    last_sample_key: Mapped[str | None] = mapped_column(String(64))
    last_received_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    last_triggered_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    last_reset_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    evaluation_status: Mapped[str] = mapped_column(String(32))
    evaluation_reason: Mapped[str] = mapped_column(Text)
    checked_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    trigger_count: Mapped[int] = mapped_column(Integer, default=0)


class AlertEvent(Base):
    __tablename__ = "t_alert_log"
    __table_args__ = (
        UniqueConstraint(
            "rule_id", "trigger_number", name="uq_alert_log_rule_trigger"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    rule_id: Mapped[str] = mapped_column(ForeignKey("t_alert_rule.id"), index=True)
    rule_version: Mapped[int] = mapped_column(Integer)
    trigger_number: Mapped[int] = mapped_column(Integer)
    rule_name: Mapped[str] = mapped_column(String(80))
    security_id: Mapped[str] = mapped_column(String(36))
    symbol: Mapped[str] = mapped_column(String(40))
    rule_type: Mapped[str] = mapped_column(String(24))
    mode: Mapped[str] = mapped_column(String(16))
    value: Mapped[str] = mapped_column(String(128))
    threshold: Mapped[str] = mapped_column(String(34))
    reason: Mapped[str] = mapped_column(Text)
    sample_key: Mapped[str] = mapped_column(String(64))
    rule_snapshot: Mapped[dict] = mapped_column(JSON)
    quote: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=utcnow)
    outbox_id: Mapped[str | None] = mapped_column(String(36))
