import json
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import func, select

from cross_market.modules.portfolio.application.accounts import account
from cross_market.modules.portfolio.application.replay import entries, fact, rebuild
from cross_market.modules.portfolio.application.schemas import PortfolioEntry
from cross_market.modules.portfolio.domain.replay import ReplayError, amounts, formatted
from cross_market.modules.portfolio.infrastructure.models import CashTransaction, Entry
from cross_market.modules.securities.application.service import get_securities, get_security
from cross_market.shared.exceptions import AppError


async def serialize(session, rows):
    securities = await get_securities(session, [r.security_id for r in rows if r.security_id])
    result = []
    for row in rows:
        security = securities.get(row.security_id)
        data = {
            key: getattr(row, key)
            for key in PortfolioEntry.model_fields
            if key not in {"symbol", "security_name"}
        }
        result.append(
            PortfolioEntry(
                **data,
                symbol=security.symbol if security else None,
                security_name=security.name if security else None,
            )
        )
    return result


def payload_hash(payload):
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


async def duplicate(session, account_id, request_id, digest):
    row = await session.scalar(
        select(Entry).where(Entry.account_id == account_id, Entry.request_id == request_id)
    )
    if row is not None and row.request_hash != digest:
        raise AppError(409, "IDEMPOTENCY_CONFLICT", "请求ID已用于不同内容")
    return row


def writable(row, rows):
    if not row.is_active:
        raise AppError(409, "ACCOUNT_INACTIVE", "账户已停用")
    if len(rows) >= 10000:
        raise AppError(409, "LEDGER_LIMIT_EXCEEDED", "账户流水已达10000条上限")


async def persist(session, owner, row, rows):
    row.id = str(uuid4())
    row.sequence = owner.next_sequence
    owner.next_sequence += 1
    owner.version += 1
    session.add(row)
    await session.flush()
    await session.refresh(row)
    session.add(CashTransaction(account_id=owner.id, entry_id=row.id, cash_delta=row.cash_delta))
    await rebuild(session, owner.id, [*rows, row])
    await session.flush()
    return (await serialize(session, [row]))[0]


async def create_entry(session, account_id, body):
    owner = await account(session, account_id, lock=True)
    payload = body.model_dump(mode="json")
    digest = payload_hash(payload)
    existing = await duplicate(session, account_id, body.request_id, digest)
    if existing:
        return (await serialize(session, [existing]))[0]
    rows = await entries(session, account_id)
    writable(owner, rows)
    if body.security_id:
        security = await get_security(session, body.security_id)
        if security.status != "ACTIVE":
            raise AppError(409, "SECURITY_INACTIVE", "证券已停用")
        if security.currency != owner.currency:
            raise AppError(409, "CURRENCY_MISMATCH", "证券与账户币种不匹配")
        quantity = Decimal(body.quantity)
        if security.market in {"CN", "HK"} and quantity != quantity.to_integral_value():
            raise AppError(422, "INVALID_QUANTITY", "此市场数量必须为整数股")
    row = Entry(
        **body.model_dump(),
        account_id=account_id,
        currency=owner.currency,
        request_hash=digest,
        request_payload=payload,
        status="ACTIVE",
    )
    try:
        gross, cash = amounts(fact(row))
        row.gross_amount, row.cash_delta = formatted(gross), formatted(cash)
    except ReplayError as error:
        raise AppError(409, "LEDGER_REPLAY_INVALID", str(error)) from error
    return await persist(session, owner, row, rows)


async def reverse_entry(session, account_id, entry_id, body):
    owner = await account(session, account_id, lock=True)
    payload = {**body.model_dump(mode="json"), "entry_id": entry_id, "kind": "REVERSAL"}
    digest = payload_hash(payload)
    existing = await duplicate(session, account_id, body.request_id, digest)
    if existing:
        return (await serialize(session, [existing]))[0]
    rows = await entries(session, account_id)
    writable(owner, rows)
    original = next((row for row in rows if row.id == entry_id), None)
    if original is None:
        raise AppError(404, "ENTRY_NOT_FOUND", "流水不存在")
    if original.kind == "REVERSAL":
        raise AppError(409, "REVERSAL_NOT_ALLOWED", "不能冲正冲正记录")
    if original.status == "REVERSED":
        raise AppError(409, "ENTRY_ALREADY_REVERSED", "原流水已冲正")
    row = Entry(
        account_id=account_id,
        request_id=body.request_id,
        request_hash=digest,
        request_payload=payload,
        kind="REVERSAL",
        occurred_at=datetime.now(UTC),
        security_id=original.security_id,
        currency=owner.currency,
        **{
            key: getattr(original, key)
            for key in ("quantity", "price", "amount", "fee", "tax", "gross_amount")
        },
        cash_delta=formatted(Decimal(original.cash_delta).copy_negate()),
        status="ACTIVE",
        reversal_of_id=original.id,
        note=body.reason,
    )
    original.status = "REVERSED"
    result = await persist(session, owner, row, rows)
    original.reversed_by_id = row.id
    await session.flush()
    return result


async def list_ledger(session, account_id, page=1, page_size=20):
    await account(session, account_id)
    total = await session.scalar(
        select(func.count()).select_from(Entry).where(Entry.account_id == account_id)
    )
    rows = list(
        await session.scalars(
            select(Entry)
            .where(Entry.account_id == account_id)
            .order_by(Entry.occurred_at.desc(), Entry.sequence.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return {
        "items": await serialize(session, rows),
        "total": total,
        "page": page,
        "page_size": page_size,
    }
