from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from cross_market.shared.database import Base


class Security(Base):
    __tablename__ = "t_security"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    symbol: Mapped[str] = mapped_column(String(40), unique=True)
    market: Mapped[str] = mapped_column(String(2))
    exchange: Mapped[str] = mapped_column(String(10))
    security_type: Mapped[str] = mapped_column(String(10))
    name: Mapped[str] = mapped_column(String(120))
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE")
    source: Mapped[str] = mapped_column(String(10), default="MANUAL")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
