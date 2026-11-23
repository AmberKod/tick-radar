from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from cross_market.modules.alerts.infrastructure.models import TIMESTAMP, new_id, utcnow
from cross_market.shared.database import Base


class AlertSchedule(Base):
    __tablename__ = "t_alert_schedule"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(80))
    exchange: Mapped[str] = mapped_column(String(8))
    times: Mapped[list] = mapped_column(JSON)
    message: Mapped[str] = mapped_column(String(1000))
    grace_seconds: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=utcnow)


class AlertScheduleRun(Base):
    __tablename__ = "t_alert_schedule_run"
    __table_args__ = (
        UniqueConstraint(
            "schedule_id", "session_date", "local_time", name="uq_alert_schedule_run_slot"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    schedule_id: Mapped[str] = mapped_column(ForeignKey("t_alert_schedule.id"), index=True)
    schedule_name: Mapped[str] = mapped_column(String(80))
    schedule_version: Mapped[int] = mapped_column(Integer)
    exchange: Mapped[str] = mapped_column(String(8))
    session_date: Mapped[date] = mapped_column(Date)
    local_time: Mapped[str] = mapped_column(String(5))
    scheduled_at: Mapped[datetime] = mapped_column(TIMESTAMP)
    status: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(Text)
    rule_snapshot: Mapped[dict] = mapped_column(JSON)
    calendar: Mapped[dict] = mapped_column(JSON)
    outbox_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=utcnow)
