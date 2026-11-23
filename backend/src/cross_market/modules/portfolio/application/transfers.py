from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from cross_market.modules.portfolio.application.accounts import account, lock_sqlite
from cross_market.modules.portfolio.application.ledger import payload_hash, writable
from cross_market.modules.portfolio.application.replay import fact, rebuild
from cross_market.modules.portfolio.application.transfer_schemas import PortfolioTransfer
from cross_market.modules.portfolio.domain.replay import amounts, formatted
from cross_market.modules.portfolio.domain.transfers import implied_rate
from cross_market.modules.portfolio.infrastructure.models import CashTransaction, Entry
from cross_market.modules.portfolio.infrastructure.transfer_models import Transfer
from cross_market.shared.exceptions import AppError


def current(statement):
    return statement.with_for_update().execution_options(populate_existing=True)


def conflict():
    return AppError(409, "IDEMPOTENCY_CONFLICT", "请求ID已用于不同内容")


async def pair_accounts(session, source_id, target_id):
    owners = {}
    for account_id in sorted((source_id, target_id)):
        owners[account_id] = await account(session, account_id, lock=True)
    return owners


async def pair_entries(session, owners, request_id):
    result = {}
    for account_id in sorted(owners):
        rows = list(
            await session.scalars(
                current(
                    select(Entry).where(Entry.account_id == account_id).order_by(Entry.sequence)
                )
            )
        )
        writable(owners[account_id], rows)
        if any(row.request_id == request_id for row in rows):
            raise conflict()
        result[account_id] = rows
    return result


async def by_request(session, request_id, digest, *, reversal=False, latest=False):
    column = Transfer.reversal_request_id if reversal else Transfer.request_id
    query = select(Transfer).where(column == request_id)
    # 缺失键不做加锁读，避免不同账户同时插入同一索引间隙而死锁。
    # 只有唯一冲突已证明存在赢家时，才按请求键做当前读。
    if latest:
        row = await session.scalar(current(query))
    else:
        identity = await session.scalar(select(Transfer.id).where(column == request_id))
        row = (
            await session.scalar(current(select(Transfer).where(Transfer.id == identity)))
            if identity is not None
            else None
        )
    if row is not None:
        stored = row.reversal_request_hash if reversal else row.request_hash
        if stored != digest:
            raise conflict()
    return row


async def get_transfer(session, transfer_id):
    row = await session.get(Transfer, transfer_id)
    if row is None:
        raise AppError(404, "TRANSFER_NOT_FOUND", "划转不存在")
    return PortfolioTransfer.model_validate(row)


async def list_transfers(session, page=1, page_size=20, account_id=None):
    condition = []
    if account_id is not None:
        await account(session, account_id)
        condition.append(
            or_(Transfer.source_account_id == account_id, Transfer.target_account_id == account_id)
        )
    total = await session.scalar(select(func.count()).select_from(Transfer).where(*condition))
    rows = await session.scalars(
        select(Transfer)
        .where(*condition)
        .order_by(Transfer.occurred_at.desc(), Transfer.created_at.desc(), Transfer.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return {
        "items": [PortfolioTransfer.model_validate(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def new_entry(owner, transfer_id, entry_id, request_id, digest, payload, **values):
    row = Entry(
        id=entry_id,
        account_id=owner.id,
        transfer_id=transfer_id,
        sequence=owner.next_sequence,
        request_id=request_id,
        request_hash=digest,
        request_payload=payload,
        currency=owner.currency,
        security_id=None,
        quantity="0.00000000",
        price="0.00000000",
        tax="0.00000000",
        status="ACTIVE",
        **values,
    )
    owner.next_sequence += 1
    owner.version += 1
    return row


async def persist_pair(session, owners, rows, added):
    session.add_all(added)
    await session.flush()
    for row in added:
        session.add(
            CashTransaction(account_id=row.account_id, entry_id=row.id, cash_delta=row.cash_delta)
        )
    for account_id in sorted(owners):
        await rebuild(
            session,
            account_id,
            [*rows[account_id], *(row for row in added if row.account_id == account_id)],
        )
    await session.flush()


async def create_transfer(session, body):
    owners = await pair_accounts(session, body.source_account_id, body.target_account_id)
    payload = body.model_dump(mode="json")
    digest = payload_hash(payload)
    existing = await by_request(session, body.request_id, digest)
    if existing is not None:
        return PortfolioTransfer.model_validate(existing)
    source, target = owners[body.source_account_id], owners[body.target_account_id]
    if source.currency == target.currency and body.source_amount != body.target_amount:
        raise AppError(422, "TRANSFER_AMOUNT_MISMATCH", "同币种划转两边本金必须相等")
    rows = await pair_entries(session, owners, body.request_id)
    try:
        async with session.begin_nested():
            row = Transfer(
                **body.model_dump(),
                id=str(uuid4()),
                request_hash=digest,
                request_payload=payload,
                source_account_name=source.name,
                target_account_name=target.name,
                source_currency=source.currency,
                target_currency=target.currency,
                implied_rate=implied_rate(body.source_amount, body.target_amount),
                source_entry_id=str(uuid4()),
                target_entry_id=str(uuid4()),
            )
            session.add(row)
            await session.flush()
            added = []
            for owner, kind, amount, fee, entry_id in (
                (source, "TRANSFER_OUT", body.source_amount, body.source_fee, row.source_entry_id),
                (target, "TRANSFER_IN", body.target_amount, "0.00000000", row.target_entry_id),
            ):
                entry = new_entry(
                    owner,
                    row.id,
                    entry_id,
                    body.request_id,
                    digest,
                    {**payload, "kind": kind},
                    kind=kind,
                    occurred_at=body.occurred_at,
                    amount=amount,
                    fee=fee,
                    note=body.note,
                )
                gross, cash = amounts(fact(entry))
                entry.gross_amount, entry.cash_delta = formatted(gross), formatted(cash)
                added.append(entry)
            await persist_pair(session, owners, rows, added)
            result = PortfolioTransfer.model_validate(row)
    except IntegrityError as error:
        winner = await by_request(session, body.request_id, digest, latest=True)
        if winner is None:
            raise conflict() from error
        return PortfolioTransfer.model_validate(winner)
    return result


async def reverse_transfer(session, transfer_id, body):
    await lock_sqlite(session)
    initial = await session.get(Transfer, transfer_id)
    if initial is None:
        raise AppError(404, "TRANSFER_NOT_FOUND", "划转不存在")
    owners = await pair_accounts(session, initial.source_account_id, initial.target_account_id)
    row = await session.scalar(current(select(Transfer).where(Transfer.id == transfer_id)))
    payload = {**body.model_dump(mode="json"), "transfer_id": transfer_id, "kind": "REVERSAL"}
    digest = payload_hash(payload)
    # 初读可早于等待账户锁；同笔冲正直接核对锁后最新行，避免旧快照漏掉赢家。
    if row.reversal_request_id == body.request_id:
        if row.reversal_request_hash != digest:
            raise conflict()
        return PortfolioTransfer.model_validate(row)
    existing = await by_request(session, body.request_id, digest, reversal=True)
    if existing is not None:
        return PortfolioTransfer.model_validate(existing)
    if row.status == "REVERSED":
        raise AppError(409, "TRANSFER_ALREADY_REVERSED", "划转已整笔冲正")
    rows = await pair_entries(session, owners, body.request_id)
    originals = []
    for account_id, entry_id, kind in (
        (row.source_account_id, row.source_entry_id, "TRANSFER_OUT"),
        (row.target_account_id, row.target_entry_id, "TRANSFER_IN"),
    ):
        original = next((entry for entry in rows[account_id] if entry.id == entry_id), None)
        if (
            original is None
            or original.transfer_id != row.id
            or original.status != "ACTIVE"
            or original.kind != kind
        ):
            raise AppError(409, "TRANSFER_ENTRY_INVALID", "划转关联流水不一致")
        originals.append(original)
    try:
        async with session.begin_nested():
            timestamp = datetime.now(UTC)
            added = []
            for original in originals:
                audit = new_entry(
                    owners[original.account_id],
                    row.id,
                    str(uuid4()),
                    body.request_id,
                    digest,
                    payload,
                    kind="REVERSAL",
                    occurred_at=timestamp,
                    amount=original.amount,
                    fee=original.fee,
                    gross_amount=original.gross_amount,
                    cash_delta=formatted(Decimal(original.cash_delta).copy_negate()),
                    reversal_of_id=original.id,
                    note=body.reason,
                )
                original.status, original.reversed_by_id = "REVERSED", audit.id
                added.append(audit)
            row.status, row.reversed_at = "REVERSED", timestamp
            row.source_reversal_entry_id, row.target_reversal_entry_id = (added[0].id, added[1].id)
            row.reversal_request_id, row.reversal_request_hash = body.request_id, digest
            row.reversal_reason = body.reason
            await persist_pair(session, owners, rows, added)
            result = PortfolioTransfer.model_validate(row)
    except IntegrityError as error:
        winner = await by_request(session, body.request_id, digest, reversal=True, latest=True)
        if winner is None:
            raise conflict() from error
        return PortfolioTransfer.model_validate(winner)
    return result
