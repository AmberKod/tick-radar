import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from cross_market.modules.alerts.infrastructure import models as alert_models  # noqa: F401
from cross_market.modules.alerts.infrastructure import schedule_models  # noqa: F401
from cross_market.modules.indicators.infrastructure.models import IndicatorProfile  # noqa: F401
from cross_market.modules.notifications.infrastructure import models as notification_models  # noqa: F401
from cross_market.modules.portfolio.infrastructure import models as portfolio_models  # noqa: F401
from cross_market.modules.securities.infrastructure.models import Security  # noqa: F401
from cross_market.modules.system.infrastructure.models import SystemSetting  # noqa: F401
from cross_market.modules.watchlist.infrastructure.models import WatchlistGroup, WatchlistItem  # noqa: F401
from cross_market.shared.config import Settings
from cross_market.shared.database import Base

config = context.config
# 测试可显式传入 SQLite URL；正式环境仅从 TR_MYSQL_* 装配。
url = config.attributes.get("connection_url") or Settings().database_url


def migrate(connection):
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()


async def online():
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(migrate)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(online())
