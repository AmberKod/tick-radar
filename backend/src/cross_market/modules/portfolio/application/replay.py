from decimal import Decimal

from sqlalchemy import delete, select

from cross_market.modules.portfolio.application.schemas import utc
from cross_market.modules.portfolio.domain.replay import Fact, ReplayError, formatted, replay
from cross_market.modules.portfolio.infrastructure.models import Entry, PositionProjection
from cross_market.shared.exceptions import AppError


async def entries(session, account_id, *, lock=False):
    query = select(Entry).where(Entry.account_id == account_id)
    if lock:
        # 写事务已持有账户锁，当前读防止等待锁前的旧快照漏掉已提交流水。
        query = query.with_for_update().execution_options(populate_existing=True)
    return list(await session.scalars(query))


def fact(row):
    return Fact(
        kind=row.kind,
        security_id=row.security_id,
        **{
            key: Decimal(getattr(row, key)) for key in ("quantity", "price", "amount", "fee", "tax")
        },
    )


def calculate(rows):
    active = sorted(
        (row for row in rows if row.status == "ACTIVE" and row.kind != "REVERSAL"),
        key=lambda row: (utc(row.occurred_at), row.sequence),
    )
    try:
        return replay(fact(row) for row in active)
    except ReplayError as error:
        raise AppError(409, "LEDGER_REPLAY_INVALID", str(error)) from error


async def rebuild(session, account_id, rows):
    result = calculate(rows)
    await session.execute(
        delete(PositionProjection).where(PositionProjection.account_id == account_id)
    )
    for security_id, position in result.positions.items():
        session.add(
            PositionProjection(
                account_id=account_id,
                security_id=security_id,
                **{
                    key: formatted(getattr(position, key))
                    for key in ("quantity", "total_cost", "realized_pnl", "dividend_income")
                },
            )
        )
    await session.flush()
    return result
