import re
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SecurityCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    symbol: str = Field(max_length=40)
    exchange: Literal["SSE", "SZSE", "BSE", "HKEX", "NASDAQ", "NYSE", "AMEX"]
    security_type: Literal["STOCK", "ETF", "ADR"]
    name: str = Field(min_length=1, max_length=120)

    @field_validator("symbol", "exchange", "security_type", mode="before")
    @classmethod
    def normalize(cls, value):
        return value.strip().upper() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_identity(self):
        market, separator, ticker = self.symbol.partition(":")
        valid = False
        if separator and market == "CN" and re.fullmatch(r"[0-9]{6}", ticker):
            if self.security_type == "ETF":
                valid = (self.exchange == "SSE" and ticker.startswith("5")) or (
                    self.exchange == "SZSE" and ticker.startswith("15")
                )
            elif self.security_type == "STOCK":
                valid = (
                    (self.exchange == "SSE" and ticker.startswith("6"))
                    or (self.exchange == "SZSE" and ticker.startswith(("0", "3")))
                    or (self.exchange == "BSE" and ticker.startswith(("4", "8", "92")))
                )
        elif market == "HK":
            valid = bool(re.fullmatch(r"[0-9]{5}", ticker)) and self.exchange == "HKEX"
        elif market == "US":
            valid = bool(
                re.fullmatch(r"[A-Z][A-Z0-9]*(?:[.-][A-Z0-9]+)*", ticker)
            ) and self.exchange in {"NASDAQ", "NYSE", "AMEX"}
        if not valid:
            raise ValueError("证券代码与交易所不匹配")
        return self


class SecurityFromQuote(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    symbol: str = Field(max_length=40)
    exchange: Literal["SSE", "SZSE", "BSE", "HKEX", "NASDAQ", "NYSE", "AMEX"] | None = None
    security_type: Literal["STOCK", "ETF", "ADR"] = "STOCK"

    @model_validator(mode="after")
    def validate_identity(self):
        from cross_market.modules.market_data.application.symbols import resolve_exchange

        exchange = resolve_exchange(self.symbol, self.exchange)
        SecurityCreate(
            symbol=self.symbol, exchange=exchange, security_type=self.security_type, name="校验"
        )
        return self


class SecurityUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    status: Literal["ACTIVE", "INACTIVE"] | None = None

    @model_validator(mode="after")
    def no_null(self):
        if any(getattr(self, key) is None for key in self.model_fields_set):
            raise ValueError("字段不可为空")
        return self


class SecurityDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    symbol: str
    market: Literal["CN", "HK", "US"]
    exchange: Literal["SSE", "SZSE", "BSE", "HKEX", "NASDAQ", "NYSE", "AMEX"]
    security_type: Literal["STOCK", "ETF", "ADR"]
    name: str
    currency: Literal["CNY", "HKD", "USD"]
    status: Literal["ACTIVE", "INACTIVE"]
    source: Literal["MANUAL", "TENCENT_LOOKUP"]
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def utc(cls, value):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class SecurityPage(BaseModel):
    items: list[SecurityDTO]
    total: int
    page: int
    page_size: int
