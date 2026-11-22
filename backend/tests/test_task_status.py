import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

from cross_market.modules.system.infrastructure.task_status import parse_status, task_statuses


def test_task_status_preserves_last_success_but_exposes_partial_failure():
    now = datetime.now(UTC)
    last_success = now - timedelta(minutes=1)
    result = parse_status(
        json.dumps(
            {
                "state": "partial",
                "checked_at": now.isoformat(),
                "last_success_at": last_success.isoformat(),
                "symbol_count": 3,
            }
        ),
        30,
    )
    assert result.status == "partial" and result.last_success_at == last_success
    assert result.symbol_count == 3


def test_missing_stale_and_malformed_task_status_are_not_success():
    assert parse_status(None, 30).status == "waiting"
    old = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    assert parse_status(json.dumps({"state": "success", "checked_at": old}), 30).status == "stale"
    for raw in ("broken", "[]", '{"state":"success","checked_at":"bad"}'):
        assert parse_status(raw, 30).status == "unknown"


async def test_task_read_failure_does_not_report_collector_healthy():
    redis = SimpleNamespace(get=AsyncMock(side_effect=ConnectionError("private password")))
    settings = SimpleNamespace(
        market_observation_enabled=True, quote_refresh_interval_seconds=30, probe_timeout_seconds=1
    )
    tasks = await task_statuses(redis, settings)
    assert [task.status for task in tasks] == ["unknown", "unknown", "unknown"]
    assert "private password" not in tasks[0].model_dump_json()


async def test_new_tasks_default_waiting_and_notifications_remain_enabled():
    redis = SimpleNamespace(get=AsyncMock(return_value=None))
    settings = SimpleNamespace(market_observation_enabled=False, probe_timeout_seconds=1)
    tasks = await task_statuses(redis, settings)
    assert [task.status for task in tasks] == ["disabled", "disabled", "waiting"]
    settings.market_observation_enabled = True
    tasks = await task_statuses(redis, settings)
    assert [task.status for task in tasks] == ["waiting", "waiting", "waiting"]
    settings.alert_observation_enabled = False
    assert (await task_statuses(redis, settings))[1].status == "disabled"


async def test_broken_fake_redis_response_is_unknown():
    redis = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(broken=True)))
    settings = SimpleNamespace(probe_timeout_seconds=1)
    assert all(task.status == "unknown" for task in await task_statuses(redis, settings))
