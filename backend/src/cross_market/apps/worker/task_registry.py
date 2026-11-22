from functools import partial

from cross_market.apps.worker.quote_collector import quote_collector


def registered_tasks(*, session_factory=None, list_targets=None, quote_service=None) -> tuple:
    if session_factory is None or list_targets is None or quote_service is None:
        return ()
    return (
        partial(
            quote_collector,
            session_factory=session_factory,
            list_targets=list_targets,
            quote_service=quote_service,
        ),
    )
