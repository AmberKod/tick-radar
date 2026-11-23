from datetime import datetime

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from cross_market.modules.portfolio.infrastructure.models import MONEY, TIME, identifier, now
from cross_market.shared.database import Base


class Transfer(Base):
    __tablename__ = "t_portfolio_transfer"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    request_id: Mapped[str] = mapped_column(String(36), unique=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    request_payload: Mapped[dict] = mapped_column(JSON)
    source_account_id: Mapped[str] = mapped_column(ForeignKey("t_account.id"), index=True)
    target_account_id: Mapped[str] = mapped_column(ForeignKey("t_account.id"), index=True)
    source_account_name: Mapped[str] = mapped_column(String(80))
    target_account_name: Mapped[str] = mapped_column(String(80))
    source_currency: Mapped[str] = mapped_column(String(3))
    target_currency: Mapped[str] = mapped_column(String(3))
    source_amount: Mapped[str] = mapped_column(MONEY)
    target_amount: Mapped[str] = mapped_column(MONEY)
    source_fee: Mapped[str] = mapped_column(MONEY)
    implied_rate: Mapped[str] = mapped_column(String(64))
    rate_basis: Mapped[str] = mapped_column(String(24), default="ACTUAL_AMOUNTS")
    occurred_at: Mapped[datetime] = mapped_column(TIME)
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE")
    note: Mapped[str] = mapped_column(String(500), default="")
    source_entry_id: Mapped[str] = mapped_column(String(36), unique=True)
    target_entry_id: Mapped[str] = mapped_column(String(36), unique=True)
    source_reversal_entry_id: Mapped[str | None] = mapped_column(String(36), unique=True)
    target_reversal_entry_id: Mapped[str | None] = mapped_column(String(36), unique=True)
    reversal_request_id: Mapped[str | None] = mapped_column(String(36), unique=True)
    reversal_request_hash: Mapped[str | None] = mapped_column(String(64))
    reversal_reason: Mapped[str | None] = mapped_column(String(500))
    reversed_at: Mapped[datetime | None] = mapped_column(TIME)
    created_at: Mapped[datetime] = mapped_column(TIME, default=now)
