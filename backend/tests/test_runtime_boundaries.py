import asyncio
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx

from cross_market.apps.api.main import create_app
from cross_market.apps.worker.main import run
from cross_market.modules.system.infrastructure.probes import InfrastructureProbes
from cross_market.shared.config import Settings
from cross_market.shared.logging import JsonFormatter


async def test_probe_timeout_marks_worker_unknown():
    async def blocked_ping():
        await asyncio.Event().wait()

    probes = InfrastructureProbes(
        None, SimpleNamespace(ping=blocked_ping), Settings(probe_timeout_seconds=0.001)
    )
    redis, worker = await probes.redis_and_worker_status()
    assert redis.status == "unhealthy"
    assert worker.status == "unknown"


async def test_internal_error_is_redacted():
    app = create_app()
    app.state.health_service = SimpleNamespace(
        status=AsyncMock(side_effect=RuntimeError("mysql://user:password@private-host"))
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as c:
        response = await c.get("/health/system")
        assert response.status_code == 500
        assert response.json()["code"] == "INTERNAL_ERROR"
        assert "password" not in response.text
        assert "private-host" not in response.text


def test_structured_log_never_formats_credentials():
    record = logging.LogRecord("test", logging.ERROR, "", 1, "password=%s", ("secret",), None)
    payload = json.loads(JsonFormatter().format(record))
    assert payload["timestamp"].endswith("+00:00")
    assert "secret" not in json.dumps(payload)
    assert payload["event"] == "runtime_log"
    assert payload["service"] == "api"
    record.trace_id = "test-trace"
    record.exception_type = "RuntimeError"
    diagnostic = json.loads(JsonFormatter("worker").format(record))
    assert diagnostic["trace_id"] == "test-trace"
    assert diagnostic["service"] == "worker"
    assert "secret" not in json.dumps(diagnostic)


async def test_worker_connection_failure_closes_client(monkeypatch):
    redis = SimpleNamespace(
        set=AsyncMock(side_effect=ConnectionError("redis://password")), aclose=AsyncMock()
    )
    monkeypatch.setattr("cross_market.apps.worker.main.Redis.from_url", lambda *a, **k: redis)
    monkeypatch.setattr("cross_market.apps.worker.main.signal.signal", lambda *a: None)
    assert await run() == 1
    redis.aclose.assert_awaited_once()
