from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from cross_market.shared.database import Base

TIME = DateTime(timezone=True).with_variant(DATETIME(fsp=6), "mysql")


class DecimalText(TypeDecorator):
    """MySQL使用DECIMAL存事实，接口仍返回精确字符串；SQLite测试避免浮点转换。"""

    impl = String(34)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(Numeric(32, 8) if dialect.name == "mysql" else String(34))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return Decimal(value) if dialect.name == "mysql" else str(value)

    def process_result_value(self, value, dialect):
        return format(Decimal(value), ".8f") if value is not None else None


MONEY = DecimalText()


def now():
    return datetime.now(UTC)


def identifier():
    return str(uuid4())


class Account(Base):
    __tablename__ = "t_account"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    name: Mapped[str] = mapped_column(String(80))
    name_key: Mapped[str] = mapped_column(String(64), unique=True)
    currency: Mapped[str] = mapped_column(String(3))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    next_sequence: Mapped[int] = mapped_column(Integer, default=1)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(TIME, default=now)
    updated_at: Mapped[datetime] = mapped_column(TIME, default=now, onupdate=now)


class Entry(Base):
    __tablename__ = "t_portfolio_transaction"
    __table_args__ = (
        UniqueConstraint("account_id", "request_id", name="uq_portfolio_request"),
        UniqueConstraint("account_id", "sequence", name="uq_portfolio_sequence"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    account_id: Mapped[str] = mapped_column(ForeignKey("t_account.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    request_id: Mapped[str] = mapped_column(String(36))
    request_hash: Mapped[str] = mapped_column(String(64))
    request_payload: Mapped[dict] = mapped_column(JSON)
    kind: Mapped[str] = mapped_column(String(12))
    occurred_at: Mapped[datetime] = mapped_column(TIME)
    security_id: Mapped[str | None] = mapped_column(ForeignKey("t_security.id"))
    currency: Mapped[str] = mapped_column(String(3))
    # 所有金额和数量统一保持八位十进制精度。
    quantity: Mapped[str] = mapped_column(MONEY, default="0.00000000")
    price: Mapped[str] = mapped_column(MONEY, default="0.00000000")
    amount: Mapped[str] = mapped_column(MONEY, default="0.00000000")
    fee: Mapped[str] = mapped_column(MONEY, default="0.00000000")
    tax: Mapped[str] = mapped_column(MONEY, default="0.00000000")
    gross_amount: Mapped[str] = mapped_column(MONEY)
    cash_delta: Mapped[str] = mapped_column(MONEY)
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE")
    reversal_of_id: Mapped[str | None] = mapped_column(
        ForeignKey("t_portfolio_transaction.id"), unique=True
    )
    reversed_by_id: Mapped[str | None] = mapped_column(String(36))
    note: Mapped[str] = mapped_column(String(2000), default="")
    created_at: Mapped[datetime] = mapped_column(TIME, default=now)


class CashTransaction(Base):
    __tablename__ = "t_cash_transaction"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    account_id: Mapped[str] = mapped_column(ForeignKey("t_account.id"))
    entry_id: Mapped[str] = mapped_column(ForeignKey("t_portfolio_transaction.id"), unique=True)
    cash_delta: Mapped[str] = mapped_column(MONEY)
    created_at: Mapped[datetime] = mapped_column(TIME, default=now)


class PositionProjection(Base):
    __tablename__ = "t_portfolio_position"
    __table_args__ = (UniqueConstraint("account_id", "security_id", name="uq_portfolio_position"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    account_id: Mapped[str] = mapped_column(ForeignKey("t_account.id"))
    security_id: Mapped[str] = mapped_column(ForeignKey("t_security.id"))
    quantity: Mapped[str] = mapped_column(MONEY)
    total_cost: Mapped[str] = mapped_column(MONEY)
    realized_pnl: Mapped[str] = mapped_column(MONEY)
    dividend_income: Mapped[str] = mapped_column(MONEY)
