from functools import partial

from cross_market.apps.worker.alert_tasks import alert_engine, notification_dispatcher
from cross_market.apps.worker.quote_collector import quote_collector


def registered_tasks(
    *, session_factory=None, list_targets=None, quote_service=None, settings=None
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
    return tuple(tasks)
