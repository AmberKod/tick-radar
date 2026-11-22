import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from cross_market.apps.api.main import create_app
from cross_market.modules.system.application.health import HealthService
from cross_market.modules.system.application.schemas import ComponentStatus
from cross_market.modules.system.infrastructure.probes import InfrastructureProbes
from cross_market.shared.config import Settings


@pytest.mark.parametrize(
    "mysql,redis,worker,expected,http_status",
    [
        ("healthy", "healthy", "healthy", "healthy", 200),
        ("healthy", "healthy", "stale", "degraded", 200),
        ("healthy", "unhealthy", "unknown", "degraded", 200),
        ("unhealthy", "healthy", "healthy", "unhealthy", 503),
    ],
)
async def test_status_contract(mysql, redis, worker, expected, http_status):
    app = create_app()
    probes = SimpleNamespace(
        mysql_status=AsyncMock(return_value=ComponentStatus(status=mysql)),
        redis_and_worker_status=AsyncMock(
            return_value=(ComponentStatus(status=redis), ComponentStatus(status=worker))
        ),
    )
    app.state.health_service = HealthService(probes, "test")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as c:
        response = await c.get("/health/ready", headers={"X-Request-ID": "test-123"})
        assert response.status_code == http_status
        payload = response.json()
        assert payload["status"] == expected
        assert payload["market_data_enabled"] is False
        assert all(task["status"] == "disabled" for task in payload["tasks"])
        assert response.headers["X-Request-ID"] == "test-123"
        assert (await c.get("/api/v1/system/status")).status_code == 200
        assert (await c.get("/health/system")).status_code == 200
        assert len((await c.get("/api/v1/system/modules")).json()["modules"]) == 10
        assert (await c.get("/health/live")).status_code == 200
        invalid = await c.get("/health/live", headers={"X-Request-ID": "bad request"})
        assert invalid.status_code == 400
        assert set(invalid.json()) == {"code", "message", "trace_id", "details"}
        missing = await c.get("/missing")
        assert missing.status_code == 404
        assert missing.json()["trace_id"] == missing.headers["X-Request-ID"]


@pytest.mark.parametrize("age,status", [(0, "healthy"), (31, "stale"), (-10, "stale")])
async def test_worker_timestamp(age, status):
    redis = SimpleNamespace(
        ping=AsyncMock(),
        get=AsyncMock(
            return_value=json.dumps(
                {
                    "worker_name": "main",
                    "status": "running",
                    "heartbeat_at": (datetime.now(UTC) - timedelta(seconds=age)).isoformat(),
                }
            )
        ),
    )
    probes = InfrastructureProbes(None, redis, Settings())
    assert (await probes.redis_and_worker_status())[1].status == status


async def test_probe_failure_redacts_secrets():
    redis = SimpleNamespace(ping=AsyncMock(side_effect=RuntimeError("redis://secret:password")))
    probes = InfrastructureProbes(None, redis, Settings())
    cache, worker = await probes.redis_and_worker_status()
    assert cache.status == "unhealthy" and worker.status == "unknown"
    assert "password" not in cache.model_dump_json()
    assert (await probes.mysql_status()).status == "unhealthy"


def test_configuration_secrets_and_url(monkeypatch):
    monkeypatch.setenv("TR_MYSQL_PASSWORD", "p@ss/word")
    settings = Settings()
    assert isinstance(settings.mysql_password, SecretStr)
    assert settings.database_url.password == "p@ss/word"
    assert "p@ss/word" not in repr(settings)


def test_invalid_settings_do_not_echo_environment_secrets():
    with pytest.raises(ValidationError) as caught:
        Settings(mysql_password="private-db-password", worker_heartbeat_interval_seconds=60)
    assert "private-db-password" not in str(caught.value)


async def test_lifespan_closes_both_resources(monkeypatch):
    engine = SimpleNamespace(dispose=AsyncMock())
    redis = SimpleNamespace(aclose=AsyncMock())
    monkeypatch.setattr("cross_market.apps.api.main.create_engine", lambda _: engine)
    monkeypatch.setattr("cross_market.apps.api.main.Redis.from_url", lambda *a, **k: redis)
    app = create_app()
    async with app.router.lifespan_context(app):
        assert app.state.health_service
    engine.dispose.assert_awaited_once()
    redis.aclose.assert_awaited_once()
