import re
import unicodedata
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from cross_market.modules.market_data.application.schemas import QuoteDTO
from cross_market.shared.identifiers import EntityId

RuleType = Literal["PRICE_CROSS_UP", "PRICE_CROSS_DOWN", "DAY_CHANGE_ABOVE", "DAY_CHANGE_BELOW"]
Mode = Literal["OBSERVATION", "REALTIME"]
Version = Annotated[int, Field(strict=True, ge=1)]


class AlertRuleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80, strict=True)
    security_id: EntityId
    rule_type: RuleType
    mode: Mode = "OBSERVATION"
    threshold: str
    reset_threshold: str
    cooldown_seconds: int = Field(default=300, strict=True, ge=0, le=86400)
    enabled: bool = Field(default=False, strict=True)

    @field_validator("name", mode="before")
    @classmethod
    def name_clean(cls, value):
        if isinstance(value, str):
            if any(unicodedata.category(char).startswith("C") for char in value):
                raise ValueError("名称不可含控制字符")
            return value.strip()
        return value

    @model_validator(mode="after")
    def thresholds(self):
        price = self.rule_type.startswith("PRICE")
        pattern = r"[0-9]{1,16}(?:\.[0-9]{1,8})?" if price else r"-?[0-9]{1,16}(?:\.[0-9]{1,8})?"
        if not all(
            re.fullmatch(pattern, value) for value in (self.threshold, self.reset_threshold)
        ):
            raise ValueError("阈值须为最多16位整数、8位小数的字符串")
        threshold, reset = Decimal(self.threshold), Decimal(self.reset_threshold)
        if price and (threshold <= 0 or reset <= 0):
            raise ValueError("价格阈值必须大于零")
        upward = self.rule_type in {"PRICE_CROSS_UP", "DAY_CHANGE_ABOVE"}
        if (upward and reset >= threshold) or (not upward and reset <= threshold):
            raise ValueError("复位阈值方向不正确")
        return self


class AlertRuleUpdate(AlertRuleCreate):
    version: Version


class AlertResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Version


class UTCResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @field_validator("*", mode="before")
    @classmethod
    def utc(cls, value):
        if isinstance(value, datetime):
            return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return value


class AlertStateResponse(UTCResponse):
    phase: Literal["DISABLED", "ARMED", "TRIGGERED"]
    last_value: str | None
    last_sample_key: str | None
    last_received_at: AwareDatetime | None
    last_triggered_at: AwareDatetime | None
    last_reset_at: AwareDatetime | None
    evaluation_status: str
    evaluation_reason: str
    checked_at: AwareDatetime | None
    trigger_count: int


class AlertRuleResponse(UTCResponse):
    id: str
    name: str
    security_id: str
    symbol: str
    security_name: str
    rule_type: RuleType
    mode: Mode
    threshold: str
    reset_threshold: str
    cooldown_seconds: int
    enabled: bool
    version: int
    created_at: AwareDatetime
    updated_at: AwareDatetime
    state: AlertStateResponse


class AlertRulesResponse(BaseModel):
    items: list[AlertRuleResponse]


class AlertEventResponse(UTCResponse):
    id: str
    rule_id: str
    rule_name: str
    rule_version: int
    security_id: str
    symbol: str
    rule_type: RuleType
    mode: Mode
    value: str
    threshold: str
    reason: str
    quote: QuoteDTO
    created_at: AwareDatetime
    outbox_id: str | None


class AlertEventPage(BaseModel):
    items: list[AlertEventResponse]
    total: int
    page: int
    page_size: int


class AlertPreviewResponse(BaseModel):
    rule_id: str
    eligible: bool
    would_trigger: bool
    value: str | None
    status: str
    reason: str
    quote: QuoteDTO | None
    state_before: AlertStateResponse
    state_after: AlertStateResponse
    observation_only: Literal[True] = True
