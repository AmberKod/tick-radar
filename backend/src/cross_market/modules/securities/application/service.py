from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from cross_market.modules.securities.application.schemas import SecurityDTO, SecurityPage
from cross_market.modules.securities.infrastructure.models import Security
from cross_market.shared.exceptions import AppError


async def get_security(session: AsyncSession, security_id: str) -> SecurityDTO:
    security = await session.scalar(select(Security).where(Security.id == security_id))
    if security is None:
        raise AppError(404, "SECURITY_NOT_FOUND", "证券不存在")
    return SecurityDTO.model_validate(security)


async def get_securities(session: AsyncSession, ids: list[str]) -> dict[str, SecurityDTO]:
    rows = await session.scalars(select(Security).where(Security.id.in_(ids)))
    return {row.id: SecurityDTO.model_validate(row) for row in rows}


async def create_security(session, body):
    market = body.symbol.split(":")[0]
    row = Security(
        **body.model_dump(),
        market=market,
        currency={"CN": "CNY", "HK": "HKD", "US": "USD"}[market],
        source="MANUAL",
    )
    session.add(row)
    await session.flush()
    return SecurityDTO.model_validate(row)


async def create_from_quote(session, body, quote_service):
    from cross_market.modules.market_data.application.symbols import resolve_exchange

    response = await quote_service.get_quotes([body.symbol], refresh=True)
    quote = response.quotes[0]
    if not quote.name or not quote.price or not quote.provider_symbol or quote.error:
        raise AppError(422, "QUOTE_LOOKUP_FAILED", "无法验证该证券的公开报价")
    exchange = resolve_exchange(body.symbol, body.exchange)
    if quote.provider_exchange is not None and quote.provider_exchange != exchange:
        raise AppError(422, "QUOTE_EXCHANGE_MISMATCH", "供应商报价交易所与所选交易所不匹配")
    existing = await session.scalar(select(Security).where(Security.symbol == body.symbol))
    if existing is not None:
        if existing.exchange != exchange or existing.security_type != body.security_type:
            raise AppError(409, "SECURITY_IDENTITY_CONFLICT", "已有证券的交易所或类型与请求不一致")
        return SecurityDTO.model_validate(existing)
    row = Security(
        symbol=body.symbol,
        exchange=exchange,
        security_type=body.security_type,
        market=quote.market,
        currency=quote.currency,
        name=quote.name,
        source="TENCENT_LOOKUP",
    )
    session.add(row)
    await session.flush()
    return SecurityDTO.model_validate(row)


async def list_securities(session, *, q="", market=None, page=1, page_size=20):
    statement = select(Security)
    if market is not None:
        statement = statement.where(Security.market == market)
    if q.strip():
        statement = statement.where(
            or_(
                Security.symbol.contains(q.strip().upper(), autoescape=True),
                Security.name.contains(q.strip(), autoescape=True),
            )
        )
    total = await session.scalar(select(func.count()).select_from(statement.subquery()))
    rows = await session.scalars(
        statement.order_by(Security.symbol).offset((page - 1) * page_size).limit(page_size)
    )
    return SecurityPage(
        items=[SecurityDTO.model_validate(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


async def update_security(session, security_id, body):
    await get_security(session, security_id)
    row = await session.get(Security, security_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    await session.flush()
    return SecurityDTO.model_validate(row)
