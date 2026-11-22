from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from cross_market.modules.market_data.domain.quotes import WARNING, provider_symbol


class QuoteError(BaseModel):
    code: str
    message: str


class QuoteDTO(BaseModel):
    symbol: str
    name: str | None = None
    market: Literal["CN", "HK", "US"]
    currency: Literal["CNY", "HKD", "USD"]
    currency_basis: Literal["MARKET_METADATA"] = "MARKET_METADATA"
    source: Literal["tencent_public"] = "tencent_public"
    provider_symbol: str
    provider_exchange: Literal["SSE", "SZSE", "BSE", "HKEX", "NASDAQ", "NYSE", "AMEX"] | None = None
    price: str | None = None
    prev_close: str | None = None
    change: str | None = None
    change_percent: str | None = None
    market_timestamp: datetime | None = None
    source_time_raw: str | None = None
    timestamp_semantics: Literal["VENDOR_UPDATE_UNVERIFIED"] = "VENDOR_UPDATE_UNVERIFIED"
    timestamp_timezone_basis: str = "UNVERIFIED"
    received_at: datetime | None = None
    attempted_at: datetime | None = None
    cache_age_seconds: float | None = None
    market_status: Literal["MARKET_CLOSED", "UNKNOWN"] = "UNKNOWN"
    delay_status: Literal["UNKNOWN"] = "UNKNOWN"
    quality_status: Literal["UNKNOWN", "MARKET_CLOSED", "STALE", "UNAVAILABLE", "INVALID"] = (
        "UNAVAILABLE"
    )
    error: QuoteError | None = None
    observation_only: Literal[True] = True
    warnings: list[str] = Field(
        default_factory=lambda: [
            WARNING,
            "来源未提供授权及实时时效证明，市场显示授权尚未冻结",
            "不构成投资建议",
        ]
    )


class QuotesResponse(BaseModel):
    quotes: list[QuoteDTO]
    checked_at: datetime
    observation_only: Literal[True] = True


class QuoteStreamEvent(BaseModel):
    id: str
    event: Literal["snapshot", "quote.updated", "heartbeat", "error"]
    schema_version: Literal[1] = 1
    symbols: list[str]
    quotes: list[QuoteDTO]
    checked_at: datetime
    observation_only: Literal[True] = True
    error: QuoteError | None = None


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbols: list[str] = Field(min_length=1, max_length=50)

    @field_validator("symbols")
    @classmethod
    def validate_symbols(cls, symbols):
        for symbol in symbols:
            provider_symbol(symbol)
        return symbols
