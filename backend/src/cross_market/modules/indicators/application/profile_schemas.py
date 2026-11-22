import unicodedata
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from cross_market.modules.indicators.application.schemas import IndicatorParameters
from cross_market.shared.identifiers import EntityId


class ProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(strict=True, min_length=1, max_length=80)
    timeframe: Literal["day", "m15"]
    price_adjustment: Literal["raw", "qfq", "hfq", "vendor_unverified"]
    market_scope: Literal["ALL", "CN", "HK", "US"]
    parameters: IndicatorParameters

    @field_validator("name", mode="before")
    @classmethod
    def clean_name(cls, value):
        if isinstance(value, str):
            if any(unicodedata.category(char).startswith("C") for char in value):
                raise ValueError("名称不能包含控制字符")
            return value.strip()
        return value

    @model_validator(mode="after")
    def compatible_scope(self):
        if self.timeframe == "m15":
            if self.market_scope != "CN" or self.price_adjustment != "vendor_unverified":
                raise ValueError("15分钟指标仅支持CN和vendor_unverified口径")
        elif self.price_adjustment == "vendor_unverified" or (
            self.market_scope == "US" and self.price_adjustment == "hfq"
        ):
            raise ValueError("日线指标周期、市场与复权口径不兼容")
        return self


class ProfileUpdate(ProfileInput):
    version: int = Field(strict=True, ge=1)


class ProfileResponse(BaseModel):
    id: EntityId
    name: str
    timeframe: Literal["day", "m15"]
    price_adjustment: Literal["raw", "qfq", "hfq", "vendor_unverified"]
    market_scope: Literal["ALL", "CN", "HK", "US"]
    parameters: IndicatorParameters
    algorithm_version: Literal["daily-v1", "m15-v1"]
    parameter_hash: str
    version: int = Field(ge=1)
    created_at: AwareDatetime
    updated_at: AwareDatetime


class ProfilesResponse(BaseModel):
    items: list[ProfileResponse]
