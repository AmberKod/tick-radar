import asyncio
import importlib.util
import json
import logging
from pathlib import Path
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


def test_local_env_initialization_is_private_and_never_overwrites(tmp_path, capsys, monkeypatch):
    script = Path(__file__).resolve().parents[2] / "scripts" / "init_local_env.py"
    spec = importlib.util.spec_from_file_location("init_local_env", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    template = script.parents[1] / ".env.example"
    (tmp_path / ".env.example").write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    module.main()
    content = (tmp_path / ".env").read_text(encoding="utf-8")
    values = dict(
        line.split("=", 1) for line in content.splitlines() if line and not line.startswith("#")
    )
    output = capsys.readouterr().out
    for name in ("TR_MYSQL_PASSWORD", "TR_MYSQL_ROOT_PASSWORD", "TR_API_TOKEN"):
        assert len(values[name]) >= 40
        assert values[name] not in output
    assert (
        len(
            {
                values[name]
                for name in ("TR_MYSQL_PASSWORD", "TR_MYSQL_ROOT_PASSWORD", "TR_API_TOKEN")
            }
        )
        == 3
    )
    try:
        module.main()
    except SystemExit:
        pass
    else:
        raise AssertionError("已有配置必须拒绝覆盖")
    assert (tmp_path / ".env").read_text(encoding="utf-8") == content


def test_invalid_env_template_does_not_create_partial_config(tmp_path, monkeypatch):
    script = Path(__file__).resolve().parents[2] / "scripts" / "init_local_env.py"
    spec = importlib.util.spec_from_file_location("init_invalid_env", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / ".env.example").write_text("TR_API_TOKEN=\n", encoding="utf-8")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    try:
        module.main()
    except SystemExit:
        pass
    else:
        raise AssertionError("损坏模板必须拒绝生成")
    assert not (tmp_path / ".env").exists()


async def test_worker_connection_failure_closes_client(monkeypatch):
    redis = SimpleNamespace(
        set=AsyncMock(side_effect=ConnectionError("redis://password")), aclose=AsyncMock()
    )
    monkeypatch.setattr("cross_market.apps.worker.main.Redis.from_url", lambda *a, **k: redis)
    monkeypatch.setattr("cross_market.apps.worker.main.signal.signal", lambda *a: None)
    assert await run() == 1
    redis.aclose.assert_awaited_once()
