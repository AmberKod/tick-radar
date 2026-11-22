import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal
from unicodedata import category

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from cross_market.shared.identifiers import EntityId


def decimal_string(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,16}(?:\.[0-9]{1,8})?", value):
        raise ValueError("数值必须为最多16位整数及8位小数的非负十进制字符串")
    return format(Decimal(value), ".8f")


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


Number = Annotated[str, BeforeValidator(decimal_string)]
Timestamp = Annotated[AwareDatetime, BeforeValidator(utc)]
Name = Annotated[str, Field(strict=True, min_length=1, max_length=80), AfterValidator(str.strip)]
Kind = Literal["DEPOSIT", "WITHDRAWAL", "BUY", "SELL", "DIVIDEND", "FEE"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class PortfolioAccountCreate(StrictModel):
    name: str = Field(strict=True)
    currency: Literal["CNY", "HKD", "USD"]

    @field_validator("name")
    @classmethod
    def name_valid(cls, value):
        value = value.strip()
        if not 1 <= len(value) <= 80 or any(category(char).startswith("C") for char in value):
            raise ValueError("名称长度必须在1至80之间且不能包含控制字符")
        return value


class PortfolioAccountUpdate(StrictModel):
    name: str = Field(strict=True)
    is_active: bool = Field(strict=True)
    name_valid = field_validator("name")(PortfolioAccountCreate.name_valid.__func__)


class PortfolioAccount(StrictModel):
    id: str
    name: str
    currency: str
    is_active: bool
    created_at: Timestamp
    updated_at: Timestamp


class PortfolioAccountList(StrictModel):
    items: list[PortfolioAccount]


class PortfolioEntryCreate(StrictModel):
    request_id: EntityId
    kind: Kind
    occurred_at: AwareDatetime
    security_id: EntityId | None = None
    quantity: Number = "0.00000000"
    price: Number = "0.00000000"
    amount: Number = "0.00000000"
    fee: Number = "0.00000000"
    tax: Number = "0.00000000"
    note: str = Field(default="", strict=True, max_length=2000)

    @field_validator("occurred_at")
    @classmethod
    def past(cls, value):
        if value > datetime.now(UTC):
            raise ValueError("不允许未来流水")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def shape(self):
        q, p, a, f, t = map(Decimal, (self.quantity, self.price, self.amount, self.fee, self.tax))
        if self.kind in {"BUY", "SELL"}:
            valid = self.security_id is not None and q > 0 and p > 0 and a == 0
        elif self.kind == "DIVIDEND":
            valid = self.security_id is not None and a > 0 and q == p == 0 and f + t <= a
        else:
            valid = self.security_id is None and a > 0 and q == p == f == t == 0
        if not valid:
            raise ValueError("流水字段与类型不匹配")
        return self


class PortfolioReversalCreate(StrictModel):
    request_id: EntityId
    reason: str = Field(strict=True)

    @field_validator("reason")
    @classmethod
    def reason_valid(cls, value):
        value = value.strip()
        if not 1 <= len(value) <= 500:
            raise ValueError("冲正原因长度必须在1至500之间")
        return value


class PortfolioEntry(StrictModel):
    id: str
    account_id: str
    sequence: int
    request_id: str
    kind: Literal["DEPOSIT", "WITHDRAWAL", "BUY", "SELL", "DIVIDEND", "FEE", "REVERSAL"]
    occurred_at: Timestamp
    security_id: str | None
    symbol: str | None
    security_name: str | None
    currency: str
    quantity: str
    price: str
    amount: str
    fee: str
    tax: str
    gross_amount: str
    cash_delta: str
    status: Literal["ACTIVE", "REVERSED"]
    reversal_of_id: str | None
    reversed_by_id: str | None
    note: str
    created_at: Timestamp


class PortfolioEntryPage(StrictModel):
    items: list[PortfolioEntry]
    total: int
    page: int
    page_size: int


class PortfolioPosition(StrictModel):
    security_id: str
    symbol: str
    name: str
    currency: str
    quantity: str
    total_cost: str
    average_cost: str
    realized_pnl: str
    dividend_income: str


class PortfolioSummary(StrictModel):
    account: PortfolioAccount
    cash_balance: str
    total_cost: str
    realized_pnl: str
    dividend_income: str
    standalone_fees: str
    external_net_flow: str
    positions: list[PortfolioPosition]
    entry_count: int
    checked_at: Timestamp
    calculation_version: Literal["moving-average-v1"] = "moving-average-v1"
    warnings: list[str] = Field(default_factory=list)
