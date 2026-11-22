import asyncio
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import event, inspect, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cross_market.modules.securities.infrastructure.models import Security
from cross_market.modules.system.infrastructure.models import SystemSetting
from cross_market.modules.watchlist.infrastructure.models import WatchlistGroup, WatchlistItem

ROOT = Path(__file__).resolve().parents[1]


def test_upgrade_persistence_restart_and_downgrade(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}"
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["connection_url"] = url
    command.upgrade(config, "head")

    async def write():
        engine = create_async_engine(url)
        try:
            async with async_sessionmaker(engine)() as session:
                session.add(
                    SystemSetting(
                        key="timezone", value={"zone": "UTC"}, updated_at=datetime.now(UTC)
                    )
                )
                await session.commit()
        finally:
            await engine.dispose()

    async def read_after_restart():
        engine = create_async_engine(url)
        try:
            async with async_sessionmaker(engine)() as session:
                value = await session.scalar(select(SystemSetting))
                assert value.value == {"zone": "UTC"}
        finally:
            await engine.dispose()

    asyncio.run(write())
    command.upgrade(config, "head")
    asyncio.run(read_after_restart())

    async def write_business():
        engine = create_async_engine(url)

        @event.listens_for(engine.sync_engine, "connect")
        def foreign_keys(connection, record):
            connection.execute("PRAGMA foreign_keys=ON")

        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                security = Security(
                    symbol="US:AAPL",
                    market="US",
                    exchange="NASDAQ",
                    security_type="STOCK",
                    name="Apple",
                    currency="USD",
                )
                group = WatchlistGroup(name="测试", position=0)
                session.add_all([security, group])
                await session.flush()
                session.add(
                    WatchlistItem(
                        group_id=group.id, security_id=security.id, position=0, note="持久化"
                    )
                )
                await session.commit()
        finally:
            await engine.dispose()

    async def verify_business_restart():
        engine = create_async_engine(url)
        try:
            async with async_sessionmaker(engine)() as session:
                assert (await session.scalar(select(WatchlistItem))).note == "持久化"
                assert (await session.scalar(select(Security))).symbol == "US:AAPL"
        finally:
            await engine.dispose()

    asyncio.run(write_business())
    command.upgrade(config, "head")
    asyncio.run(verify_business_restart())
    command.downgrade(config, "0001_system_settings")
    asyncio.run(read_after_restart())

    async def verify_business_removed():
        engine = create_async_engine(url)
        try:
            async with engine.connect() as connection:
                names = await connection.run_sync(lambda sync: inspect(sync).get_table_names())
                assert "system_settings" in names
                assert not {"t_security", "t_watchlist", "t_watchlist_group"}.intersection(names)
        finally:
            await engine.dispose()

    asyncio.run(verify_business_removed())
    command.downgrade(config, "base")

    async def verify_removed():
        engine = create_async_engine(url)
        try:
            async with engine.connect() as connection:
                names = await connection.run_sync(lambda sync: inspect(sync).get_table_names())
                assert "system_settings" not in names
        finally:
            await engine.dispose()

    asyncio.run(verify_removed())
    command.upgrade(config, "head")
