import asyncio
import json
from datetime import UTC, datetime
from time import monotonic

from cross_market.apps.worker.quote_collector import WRITE_STATUS


class OwnerLost(RuntimeError):
    pass


async def require_owner(runtime):
    if (
        runtime.stop_event.is_set()
        or await runtime.redis.get(runtime.settings.worker_lock_key) != runtime.owner
    ):
        raise OwnerLost("任务所有权已失效")


async def evaluate_once(runtime, *, session_factory, quote_service):
    from cross_market.modules.alerts.application.evaluation import evaluate_rules
    from cross_market.modules.alerts.application.service import list_quote_targets

    async with session_factory() as session:
        async with session.begin():
            await require_owner(runtime)
            symbols = await list_quote_targets(session, limit=200)
            await require_owner(runtime)
    # 快照等待期间不持有数据库事务，也不调用供应商。
    symbols = list(dict.fromkeys(symbols))[:200]
    quotes = []
    for start in range(0, len(symbols), 50):
        response = await quote_service.snapshot(symbols[start:start + 50])
        quotes.extend(response.quotes)
    async with session_factory() as session:
        async with session.begin():
            await require_owner(runtime)
            result = await evaluate_rules(session, quotes, datetime.now(UTC))
            await require_owner(runtime)
    evaluated, skipped = result["evaluated"], result["skipped"]
    return (
        "partial" if skipped else "success" if evaluated else "idle",
        evaluated,
        skipped,
        "RULES_SKIPPED" if skipped else "RULES_EVALUATED" if evaluated else "NO_ENABLED_RULES",
    )


async def dispatch_once(runtime, *, session_factory):
    from cross_market.modules.notifications.application.service import dispatch_pending

    async with session_factory() as session:
        async with session.begin():
            await require_owner(runtime)
            result = await dispatch_pending(session, now=datetime.now(UTC), limit=50)
            await require_owner(runtime)
    sent, failed, pending = result["sent"], result["failed"], result["pending"]
    return (
        "partial" if failed or pending else "success" if sent else "idle",
        sent,
        failed,
        "DELIVERY_INCOMPLETE" if failed or pending else "DELIVERED" if sent else "NO_PENDING",
    )


async def run_periodic(runtime, *, name, interval, callback):
    while not runtime.stop_event.is_set():
        started = monotonic()
        try:
            async with asyncio.timeout(10):
                await require_owner(runtime)
                state, count, errors, code = await callback()
        except OwnerLost:
            raise
        except TimeoutError:
            state, count, errors, code = "error", 0, 1, "TASK_TIMEOUT"
        except Exception:
            state, count, errors, code = "error", 0, 1, "TASK_FAILED"
        checked_at = datetime.now(UTC).isoformat()
        payload = {
            "task_name": name,
            "state": state,
            "last_success_at": checked_at if state == "success" else None,
            "checked_at": checked_at,
            "error_count": errors,
            "symbol_count": count,
            "duration_ms": round((monotonic() - started) * 1000),
            "last_error": code if state in {"error", "partial"} else None,
            "detail": code,
        }
        if not await runtime.redis.eval(
            WRITE_STATUS,
            2,
            runtime.settings.worker_lock_key,
            f"health:worker:task:{name}",
            runtime.owner,
            json.dumps(payload),
            max(interval * 4, 120),
        ):
            raise OwnerLost("任务所有权已失效")
        try:
            await asyncio.wait_for(runtime.stop_event.wait(), interval)
        except TimeoutError:
            pass


async def alert_engine(runtime, *, session_factory, quote_service):
    async def callback():
        return await evaluate_once(
            runtime, session_factory=session_factory, quote_service=quote_service
        )

    await run_periodic(
        runtime,
        name="alert_engine",
        interval=getattr(runtime.settings, "alert_scan_interval_seconds", 5),
        callback=callback,
    )


async def notification_dispatcher(runtime, *, session_factory):
    async def callback():
        return await dispatch_once(runtime, session_factory=session_factory)

    await run_periodic(
        runtime,
        name="notification_dispatcher",
        interval=getattr(runtime.settings, "notification_dispatch_interval_seconds", 2),
        callback=callback,
    )
