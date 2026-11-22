import asyncio
import logging
import signal
from contextlib import AsyncExitStack

import httpx
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker

from cross_market.apps.worker.runtime import WorkerRuntime
from cross_market.apps.worker.task_registry import registered_tasks
from cross_market.shared.config import Settings
from cross_market.shared.database import create_engine
from cross_market.shared.logging import configure_logging


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
        if settings.market_observation_enabled:
            from cross_market.modules.market_data.application.service import QuoteService
            from cross_market.modules.watchlist.application.service import list_quote_targets

            engine = create_engine(settings)
            resources.push_async_callback(engine.dispose)
            client = await resources.enter_async_context(
                httpx.AsyncClient(timeout=5, follow_redirects=False, trust_env=False)
            )
            runtime.tasks = registered_tasks(
                session_factory=async_sessionmaker(engine, expire_on_commit=False),
                list_targets=list_quote_targets,
                quote_service=QuoteService(client=client, redis=redis, settings=settings),
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
