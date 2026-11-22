from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, CheckConstraint, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from cross_market.shared.database import Base


class IndicatorProfile(Base):
    __tablename__ = "t_indicator_profile"
    __table_args__ = (
        UniqueConstraint("name_key", name="uq_indicator_profile_name_key"),
        CheckConstraint("version >= 1", name="ck_indicator_profile_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(80))
    name_key: Mapped[str] = mapped_column(String(64))
    timeframe: Mapped[str] = mapped_column(String(3))
    price_adjustment: Mapped[str] = mapped_column(String(20))
    market_scope: Mapped[str] = mapped_column(String(3))
    parameters: Mapped[dict] = mapped_column(JSON)
    algorithm_version: Mapped[str] = mapped_column(String(16))
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
