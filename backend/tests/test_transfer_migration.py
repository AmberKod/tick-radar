import asyncio
from datetime import datetime
from io import StringIO
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import MetaData, create_engine, event, inspect, select, text
from sqlalchemy.dialects import mysql
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateIndex, CreateTable

from cross_market.modules.portfolio.application.accounts import account, lock_sqlite
from cross_market.modules.portfolio.infrastructure.models import Account, Entry
from cross_market.modules.portfolio.infrastructure.transfer_models import Transfer
from cross_market.shared.database import Base

ROOT = Path(__file__).resolve().parents[1]
MONEY_COLUMNS = ("quantity", "price", "amount", "fee", "tax", "gross_amount", "cash_delta")


@pytest.fixture
def legacy_database(tmp_path):
    path = tmp_path / "transfer-migration.db"
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["connection_url"] = f"sqlite+aiosqlite:///{path}"
    command.upgrade(config, "0007")
    engine = create_engine(f"sqlite:///{path}")
    timestamp = datetime(2026, 1, 2, 3, 4, 5, 123456)
    metadata = MetaData()
    metadata.reflect(engine)
    with engine.begin() as connection:
        connection.execute(
            metadata.tables["t_account"].insert(),
            {
                "id": "legacy-account",
                "name": "迁移前账户",
                "name_key": "a" * 64,
                "currency": "USD",
                "is_active": True,
                "next_sequence": 2,
                "version": 2,
                "created_at": timestamp,
                "updated_at": timestamp,
            },
        )
        connection.execute(
            metadata.tables["t_portfolio_transaction"].insert(),
            {
                "id": "legacy-deposit",
                "account_id": "legacy-account",
                "sequence": 1,
                "request_id": "legacy-request",
                "request_hash": "b" * 64,
                "request_payload": {"kind": "DEPOSIT", "amount": "1234567890123456.12345678"},
                "kind": "DEPOSIT",
                "occurred_at": timestamp,
                "security_id": None,
                "currency": "USD",
                **dict.fromkeys(MONEY_COLUMNS, "0.00000000"),
                "amount": "1234567890123456.12345678",
                "gross_amount": "1234567890123456.12345678",
                "cash_delta": "1234567890123456.12345678",
                "status": "ACTIVE",
                "reversal_of_id": None,
                "reversed_by_id": None,
                "note": "保留旧入金事实与八位小数",
                "created_at": timestamp,
            },
        )
        connection.execute(
            metadata.tables["t_cash_transaction"].insert(),
            {
                "id": "legacy-cash",
                "account_id": "legacy-account",
                "entry_id": "legacy-deposit",
                "cash_delta": "1234567890123456.12345678",
                "created_at": timestamp,
            },
        )
    try:
        yield config, engine
    finally:
        engine.dispose()


def legacy_snapshot(engine):
    with engine.connect() as connection:
        return {
            name: dict(connection.execute(text(f"SELECT * FROM {name}")).mappings().one())
            for name in ("t_account", "t_portfolio_transaction", "t_cash_transaction")
        }


def assert_upgraded_schema(engine, original):
    current = legacy_snapshot(engine)
    assert current["t_portfolio_transaction"].pop("transfer_id") is None
    assert current == original
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0008"
        assert connection.scalar(text("SELECT count(*) FROM t_portfolio_transfer")) == 0
        assert compare_metadata(
            MigrationContext.configure(connection, opts={"compare_type": True}), Base.metadata
        ) == []
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
    schema = inspect(engine)
    assert "ix_t_portfolio_transaction_transfer_id" in {
        index["name"] for index in schema.get_indexes("t_portfolio_transaction")
    }
    assert any(
        foreign_key["name"] == "fk_portfolio_transaction_transfer"
        and foreign_key["constrained_columns"] == ["transfer_id"]
        and foreign_key["referred_table"] == "t_portfolio_transfer"
        and foreign_key["referred_columns"] == ["id"]
        for foreign_key in schema.get_foreign_keys("t_portfolio_transaction")
    )


def test_upgrade_0007_to_0008_preserves_legacy_deposit_and_full_metadata(legacy_database):
    config, engine = legacy_database
    original = legacy_snapshot(engine)
    command.upgrade(config, "0008")
    assert_upgraded_schema(engine, original)


def test_downgrade_and_reupgrade_preserve_legacy_facts(legacy_database):
    config, engine = legacy_database
    original = legacy_snapshot(engine)
    command.upgrade(config, "0008")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM t_portfolio_transfer")) == 0
        assert connection.scalar(
            text("SELECT count(*) FROM t_portfolio_transaction WHERE transfer_id IS NOT NULL")
        ) == 0
    command.downgrade(config, "0007")
    assert legacy_snapshot(engine) == original
    assert "t_portfolio_transfer" not in inspect(engine).get_table_names()
    assert "transfer_id" not in {
        column["name"] for column in inspect(engine).get_columns("t_portfolio_transaction")
    }
    command.upgrade(config, "0008")
    assert_upgraded_schema(engine, original)


def test_mysql_migration_and_model_ddl_types_indexes_and_foreign_keys():
    output = StringIO()
    config = Config(str(ROOT / "alembic.ini"), output_buffer=output)
    config.attributes["connection_url"] = "mysql+asyncmy://unused:unused@localhost/unused"
    command.upgrade(config, "0007:0008", sql=True)
    migration = output.getvalue()
    dialect = mysql.dialect()
    transfer = Transfer.__table__
    model = str(CreateTable(transfer).compile(dialect=dialect))
    # MySQL 将 Numeric 编译为 NUMERIC，语义等同于 DECIMAL。
    for ddl in (migration, model):
        normalized = ddl.replace("NUMERIC", "DECIMAL")
        for name in ("source_amount", "target_amount", "source_fee"):
            assert f"{name} DECIMAL(32, 8) NOT NULL" in normalized
        for name in ("occurred_at", "created_at", "reversed_at"):
            assert f"{name} DATETIME(6)" in ddl
        for name in ("source_account_id", "target_account_id"):
            assert f"FOREIGN KEY({name}) REFERENCES t_account (id)" in ddl
        for name in (
            "request_id",
            "source_entry_id",
            "target_entry_id",
            "source_reversal_entry_id",
            "target_reversal_entry_id",
            "reversal_request_id",
        ):
            assert f"UNIQUE ({name})" in ddl
    indexes = "\n".join(
        str(CreateIndex(index).compile(dialect=dialect)) for index in transfer.indexes
    )
    for name in ("source_account_id", "target_account_id"):
        expected = f"CREATE INDEX ix_t_portfolio_transfer_{name} ON t_portfolio_transfer ({name})"
        assert expected in migration
        assert expected in indexes
    assert (
        "CONSTRAINT fk_portfolio_transaction_transfer FOREIGN KEY(transfer_id) "
        "REFERENCES t_portfolio_transfer (id)"
    ) in migration
    assert "FOREIGN KEY(transfer_id) REFERENCES t_portfolio_transfer (id)" in str(
        CreateTable(Entry.__table__).compile(dialect=dialect)
    )
    entry_index = next(
        index for index in Entry.__table__.indexes
        if index.name == "ix_t_portfolio_transaction_transfer_id"
    )
    assert str(CreateIndex(entry_index).compile(dialect=dialect)) in migration


def test_sqlite_lock_restarts_for_each_transaction_on_reused_session(legacy_database):
    config, _ = legacy_database

    async def exercise():
        engine = create_async_engine(config.attributes["connection_url"])
        statements = []

        @event.listens_for(engine.sync_engine, "before_cursor_execute")
        def capture(connection, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                for finish in (session.commit, session.rollback, session.commit):
                    before = statements.count("BEGIN IMMEDIATE")
                    await lock_sqlite(session)
                    await lock_sqlite(session)
                    assert statements.count("BEGIN IMMEDIATE") == before + 1
                    assert (await account(session, "legacy-account")).id == "legacy-account"
                    await finish()
        finally:
            await engine.dispose()

    asyncio.run(exercise())


@pytest.mark.asyncio
async def test_account_default_read_does_not_generate_mysql_for_update():
    session = AsyncMock()
    session.scalar.return_value = Account(id="read-account")
    result = await account(session, "read-account")
    statement = session.scalar.call_args.args[0]
    compiled = str(statement.compile(dialect=mysql.dialect()))
    assert result.id == "read-account"
    assert "FOR UPDATE" not in compiled
    assert compiled == str(
        select(Account).where(Account.id == "read-account").compile(dialect=mysql.dialect())
    )
    session.connection.assert_not_awaited()
