from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

from cross_market.modules.portfolio.application.accounts import account
from cross_market.modules.portfolio.application.replay import calculate, entries
from cross_market.modules.portfolio.application.schemas import PortfolioAccount, PortfolioPosition
from cross_market.modules.portfolio.domain.replay import formatted
from cross_market.modules.portfolio.infrastructure.models import PositionProjection
from cross_market.modules.securities.application.service import get_securities


async def summary(session, account_id):
    owner = await account(session, account_id)
    rows = await entries(session, account_id)
    result = calculate(rows)
    securities = await get_securities(session, list(result.positions))
    positions = []
    for security_id, position in sorted(result.positions.items()):
        security = securities[security_id]
        positions.append(
            PortfolioPosition(
                security_id=security_id,
                symbol=security.symbol,
                name=security.name,
                currency=security.currency,
                **{
                    key: formatted(getattr(position, key))
                    for key in (
                        "quantity",
                        "total_cost",
                        "average_cost",
                        "realized_pnl",
                        "dividend_income",
                    )
                },
            )
        )
    return {
        "account": PortfolioAccount.model_validate(owner),
        **{
            key: formatted(getattr(result, key))
            for key in (
                "cash_balance",
                "total_cost",
                "realized_pnl",
                "dividend_income",
                "standalone_fees",
                "external_net_flow",
            )
        },
        "positions": positions,
        "entry_count": len(rows),
        "checked_at": datetime.now(UTC),
    }


async def list_quote_targets(session, limit=50):
    if not 1 <= limit <= 50:
        raise ValueError("报价目标数量必须在1至50之间")
    rows = [row for row in await session.scalars(select(PositionProjection))
            if Decimal(row.quantity) > 0]
    rows.sort(key=lambda row: (row.security_id, row.account_id))
    securities = await get_securities(session, list({row.security_id for row in rows}))
    return list(
        dict.fromkeys(
            securities[row.security_id].symbol for row in rows if row.security_id in securities
        )
    )[:limit]
