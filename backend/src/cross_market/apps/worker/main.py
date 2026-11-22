import asyncio
import logging
import signal

from redis.asyncio import Redis

from cross_market.apps.worker.runtime import WorkerRuntime
from cross_market.shared.config import Settings
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
    loop = asyncio.get_running_loop()
    previous = {}

    def stop(signum, frame):
        loop.call_soon_threadsafe(runtime.stop_event.set)

    try:
        # signal.signal 同时兼容 Windows 和 Unix 主线程入口。
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous[sig] = signal.signal(sig, stop)
        return await runtime.run()
    except Exception:
        logging.getLogger(__name__).error("", extra={"event": "worker_runtime_failed"})
        return 1
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        await redis.aclose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
