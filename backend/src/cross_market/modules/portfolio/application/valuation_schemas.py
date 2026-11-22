from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field

from cross_market.modules.market_data.application.schemas import QuoteDTO


class ValuedPortfolioPosition(BaseModel):
    security_id: str
    symbol: str
    name: str
    currency: str
    quantity: str
    total_cost: str
    average_cost: str
    realized_pnl: str
    dividend_income: str
    price: str | None = None
    market_value: str | None = None
    unrealized_pnl: str | None = None
    quote: QuoteDTO | None = None


class PortfolioValuationResponse(BaseModel):
    account_id: str
    currency: Literal["CNY", "HKD", "USD"]
    cash_balance: str
    known_market_value: str
    market_value: str | None
    unrealized_pnl: str | None
    net_asset_value: str | None
    valued_positions: int
    total_positions: int
    complete: bool
    positions: list[ValuedPortfolioPosition]
    checked_at: AwareDatetime
    observation_only: Literal[True] = True
    warnings: list[str] = Field(default_factory=list)
