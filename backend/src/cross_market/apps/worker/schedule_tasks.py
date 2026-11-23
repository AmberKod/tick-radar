from datetime import UTC, datetime

from cross_market.apps.worker.alert_tasks import require_owner, run_periodic


async def schedule_once(runtime, *, session_factory, calendar):
    from cross_market.modules.alerts.application.schedules import evaluate_schedules

    async with session_factory() as session:
        async with session.begin():
            await require_owner(runtime)
            result = await evaluate_schedules(session, calendar, datetime.now(UTC))
            await require_owner(runtime)
    evaluated, skipped = result["evaluated"], result["skipped"]
    return (
        "partial" if skipped else "success" if evaluated else "idle",
        result["enqueued"] + result["missed"],
        skipped,
        "CALENDAR_UNAVAILABLE" if skipped else (
            "SCHEDULES_EVALUATED" if evaluated else "NO_ENABLED_SCHEDULES"
        ),
    )


async def schedule_reminder(runtime, *, session_factory, calendar):
    async def callback():
        return await schedule_once(runtime, session_factory=session_factory, calendar=calendar)

    await run_periodic(
        runtime,
        name="schedule_reminder",
        interval=getattr(runtime.settings, "schedule_scan_interval_seconds", 5),
        callback=callback,
    )
