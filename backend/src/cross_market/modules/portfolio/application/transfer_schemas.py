from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, Field, field_validator, model_validator

from cross_market.modules.portfolio.application.schemas import Number, StrictModel, Timestamp
from cross_market.shared.identifiers import EntityId


class PortfolioTransferCreate(StrictModel):
    request_id: EntityId
    source_account_id: EntityId
    target_account_id: EntityId
    occurred_at: AwareDatetime
    source_amount: Number
    target_amount: Number
    source_fee: Number = "0.00000000"
    note: str = Field(default="", strict=True, max_length=500)

    @field_validator("occurred_at")
    @classmethod
    def past(cls, value):
        value = value.astimezone(UTC)
        if not datetime(1900, 1, 1, tzinfo=UTC) <= value <= datetime.now(UTC):
            raise ValueError("划转时间必须在1900年至当前时间之间")
        return value

    @model_validator(mode="after")
    def shape(self):
        if self.source_account_id == self.target_account_id:
            raise ValueError("划转的两个账户必须不同")
        if Decimal(self.source_amount) <= 0 or Decimal(self.target_amount) <= 0:
            raise ValueError("两边划转本金必须为正数")
        return self


class PortfolioTransfer(StrictModel):
    id: str
    request_id: str
    source_account_id: str
    target_account_id: str
    source_account_name: str
    target_account_name: str
    source_currency: str
    target_currency: str
    source_amount: str
    target_amount: str
    source_fee: str
    implied_rate: str
    rate_basis: Literal["ACTUAL_AMOUNTS"]
    occurred_at: Timestamp
    status: Literal["ACTIVE", "REVERSED"]
    note: str
    source_entry_id: str
    target_entry_id: str
    source_reversal_entry_id: str | None
    target_reversal_entry_id: str | None
    reversal_reason: str | None
    reversed_at: Timestamp | None
    created_at: Timestamp


class PortfolioTransferPage(StrictModel):
    items: list[PortfolioTransfer]
    total: int
    page: int
    page_size: int
