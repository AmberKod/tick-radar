from functools import partial

from cross_market.apps.worker.alert_tasks import alert_engine, notification_dispatcher
from cross_market.apps.worker.quote_collector import quote_collector
from cross_market.apps.worker.schedule_tasks import schedule_reminder


def registered_tasks(
    *, session_factory=None, list_targets=None, quote_service=None, settings=None, calendar=None
) -> tuple:
    if session_factory is None:
        return ()
    tasks = []
    market_enabled = getattr(settings, "market_observation_enabled", True)
    if market_enabled and list_targets is not None and quote_service is not None:
        tasks.append(
            partial(
                quote_collector,
                session_factory=session_factory,
                list_targets=list_targets,
                quote_service=quote_service,
            )
        )
    if (
        market_enabled
        and getattr(settings, "alert_observation_enabled", True)
        and quote_service is not None
    ):
        tasks.append(
            partial(alert_engine, session_factory=session_factory, quote_service=quote_service)
        )
    tasks.append(partial(notification_dispatcher, session_factory=session_factory))
    if calendar is not None and getattr(settings, "schedule_reminders_enabled", True):
        tasks.append(
            partial(schedule_reminder, session_factory=session_factory, calendar=calendar)
        )
    return tuple(tasks)
