from hashlib import sha256
from unicodedata import normalize

from sqlalchemy import func, select, text

from cross_market.modules.portfolio.application.schemas import PortfolioAccount
from cross_market.modules.portfolio.infrastructure.models import Account, Entry
from cross_market.shared.exceptions import AppError


def name_key(name):
    return sha256(normalize("NFKC", name).casefold().encode()).hexdigest()


async def lock_sqlite(session):
    connection = await session.connection()
    if connection.dialect.name == "sqlite":
        raw = await connection.get_raw_connection()
        if not raw.driver_connection.in_transaction:
            await session.execute(text("BEGIN IMMEDIATE"))


async def account(session, account_id, *, lock=False):
    if lock:
        await lock_sqlite(session)
    statement = select(Account).where(Account.id == account_id)
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    row = await session.scalar(statement)
    if row is None:
        raise AppError(404, "ACCOUNT_NOT_FOUND", "账户不存在")
    return row


async def list_accounts(session):
    rows = await session.scalars(select(Account).order_by(Account.created_at, Account.id))
    return {"items": [PortfolioAccount.model_validate(row) for row in rows]}


async def get_account(session, account_id):
    return PortfolioAccount.model_validate(await account(session, account_id))


async def unique_name(session, name, exclude=None):
    row = await session.scalar(select(Account).where(Account.name_key == name_key(name)))
    if row is not None and row.id != exclude:
        raise AppError(409, "ACCOUNT_NAME_CONFLICT", "账户名称已存在")


async def create_account(session, body):
    await lock_sqlite(session)
    await unique_name(session, body.name)
    row = Account(**body.model_dump(), name_key=name_key(body.name))
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return PortfolioAccount.model_validate(row)


async def update_account(session, account_id, body):
    row = await account(session, account_id, lock=True)
    await unique_name(session, body.name, row.id)
    row.name, row.name_key, row.is_active = body.name, name_key(body.name), body.is_active
    await session.flush()
    await session.refresh(row)
    return PortfolioAccount.model_validate(row)


async def delete_account(session, account_id):
    row = await account(session, account_id, lock=True)
    count = await session.scalar(
        select(func.count()).select_from(Entry).where(Entry.account_id == account_id)
    )
    if count:
        raise AppError(409, "ACCOUNT_NOT_EMPTY", "存在账本事实的账户不能删除")
    await session.delete(row)
    await session.flush()
