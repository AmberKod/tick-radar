import asyncio
import logging
import signal
from contextlib import AsyncExitStack

import httpx
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker

from cross_market.apps.worker.runtime import WorkerRuntime
from cross_market.apps.worker.task_registry import registered_tasks
from cross_market.modules.market_calendar.application.service import CalendarService
from cross_market.shared.config import Settings
from cross_market.shared.database import create_engine
from cross_market.shared.logging import configure_logging

_alert_collection_offset = 0


async def list_collection_targets(session, limit=50) -> list[str]:
    from cross_market.modules.alerts.application.service import list_quote_targets as alert_targets
    from cross_market.modules.portfolio.application.summary import (
        list_quote_targets as portfolio_targets,
    )
    from cross_market.modules.watchlist.application.service import (
        list_quote_targets as watchlist_targets,
    )

    if not 1 <= limit <= 50:
        raise ValueError("报价目标数量必须在1至50之间")
    holdings = await portfolio_targets(session, limit=limit)
    watchlist = await watchlist_targets(session, limit=limit)
    alerts = list(dict.fromkeys(await alert_targets(session, limit=200)))
    primary = list(dict.fromkeys([*holdings, *watchlist]))
    combined = list(dict.fromkeys([*primary, *alerts]))
    if len(combined) <= limit:
        return combined
    # 按最终保留的主目标计算候选，持仓尾部的规则也参与轮转。
    global _alert_collection_offset
    slots = min(10, limit, len(alerts))
    retained = primary[:limit - slots]
    candidates = [symbol for symbol in alerts if symbol not in retained]
    if not candidates:
        return primary[:limit]
    start = _alert_collection_offset % len(candidates)
    rotated = candidates[start:] + candidates[:start]
    _alert_collection_offset = (start + slots) % len(candidates)
    return list(dict.fromkeys([*retained, *rotated[:slots], *primary]))[:limit]


async def run() -> int:
    settings = Settings()
    configure_logging(settings.log_level, service="worker")
    redis = Redis.from_url(
        settings.redis_url.get_secret_value(),
        decode_responses=True,
        socket_connect_timeout=settings.probe_timeout_seconds,
        socket_timeout=settings.probe_timeout_seconds,
    )
    runtime = WorkerRuntime(redis, settings)
    resources = AsyncExitStack()
    resources.push_async_callback(redis.aclose)
    loop = asyncio.get_running_loop()
    previous = {}

    def stop(signum, frame):
        loop.call_soon_threadsafe(runtime.stop_event.set)

    try:
        calendar = CalendarService(settings.calendar_closed_dates)
        await calendar.warmup()
        from cross_market.modules.market_data.application.service import QuoteService

        engine = create_engine(settings)
        resources.push_async_callback(engine.dispose)
        client = await resources.enter_async_context(
            httpx.AsyncClient(timeout=5, follow_redirects=False, trust_env=False)
        )
        runtime.tasks = registered_tasks(
            session_factory=async_sessionmaker(engine, expire_on_commit=False),
            list_targets=list_collection_targets,
            quote_service=QuoteService(
                client=client, redis=redis, settings=settings, calendar=calendar
            ),
            settings=settings,
        )
        # signal.signal 同时兼容 Windows 和 Unix 主线程入口。
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous[sig] = signal.signal(sig, stop)
        return await runtime.run()
    except Exception:
        logging.getLogger(__name__).error("", extra={"event": "worker_runtime_failed"})
        return 1
    finally:
        try:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
        finally:
            await resources.aclose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
