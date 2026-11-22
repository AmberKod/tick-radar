import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from cross_market.apps.api.main import create_app
from cross_market.modules.indicators.application.profiles import name_conflict
from cross_market.modules.indicators.application.schemas import IndicatorParameters
from cross_market.shared.config import Settings

ROOT = Path(__file__).resolve().parents[1]
URL = "/api/v1/indicators/profiles"
TOKEN = {"Authorization": "Bearer test-token"}
BODY = {
    "name": "默认配置",
    "timeframe": "day",
    "price_adjustment": "raw",
    "market_scope": "ALL",
    "parameters": {},
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    url = f"sqlite+aiosqlite:///{tmp_path / 'profiles.db'}"
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["connection_url"] = url
    command.upgrade(config, "head")
    monkeypatch.setattr(
        "cross_market.apps.api.main.create_engine", lambda settings: create_async_engine(url)
    )
    with TestClient(create_app(Settings(api_token="test-token"))) as value:
        yield value


def create(client, **changes):
    response = client.post(URL, headers=TOKEN, json={**BODY, **changes})
    assert response.status_code == 201, response.text
    return response.json()


def test_crud_restart_and_metadata(client):
    first = create(client, name="  自定义配置  ")
    assert first["name"] == "自定义配置"
    assert first["version"] == 1
    assert first["algorithm_version"] == "daily-v1"
    parameters = IndicatorParameters().model_dump()
    assert first["parameters"] == parameters
    canonical = json.dumps(parameters, sort_keys=True, separators=(",", ":"))
    assert first["parameter_hash"] == hashlib.sha256(canonical.encode()).hexdigest()
    for key in ("created_at", "updated_at"):
        assert datetime.fromisoformat(first[key]).utcoffset().total_seconds() == 0
    path = f"{URL}/{first['id']}"
    assert client.get(path.upper().replace(URL.upper(), URL), headers=TOKEN).json() == first
    assert client.get(URL, headers=TOKEN).json() == {"items": [first]}
    # 新应用使用相同数据库，验证请求之外的持久化。
    with TestClient(create_app(Settings(api_token="test-token"))) as restarted:
        assert restarted.get(path, headers=TOKEN).json() == first
    updated = client.put(path, headers=TOKEN, json={**BODY, "name": "新名称", "version": 1})
    assert updated.status_code == 200, updated.text
    assert updated.json()["version"] == 2
    assert updated.json()["created_at"] == first["created_at"]
    assert client.delete(path, headers=TOKEN, params={"version": 2}).status_code == 204
    assert client.get(path, headers=TOKEN).json()["code"] == "PROFILE_NOT_FOUND"
    assert client.get(URL, headers=TOKEN).json() == {"items": []}


@pytest.mark.parametrize(
    "method,suffix", [("get", ""), ("post", ""), ("get", "/id"), ("put", "/id"), ("delete", "/id")]
)
def test_auth_all_operations(client, method, suffix):
    path = URL + suffix.replace("id", str(uuid4()))
    assert client.request(method, path).status_code == 401
    assert client.request(method, path, headers={"Authorization": "Bearer bad"}).status_code == 401
    client.app.state.settings = Settings(api_token="")
    response = client.request(method, path, headers=TOKEN)
    assert response.status_code == 503
    assert response.json()["code"] == "AUTH_NOT_CONFIGURED"


@pytest.mark.parametrize(
    "changes",
    [
        {"name": " "},
        {"name": "a" * 81},
        {"name": "a\nb"},
        {"name": "a\x00"},
        {"name": 12},
        {"name": "a\u200bb"},
        {"unexpected": 1},
        {"parameters": {"ma_period": True}},
        {"parameters": {"ma_period": "10"}},
        {"parameters": {"ma_period": 10.0}},
        {"parameters": {"extra": 1}},
        {"parameters": {"macd_fast": 13}},
        {"parameters": {"atr_period": 1}},
        {"timeframe": "weekly"},
        {"market_scope": "EU"},
        {"timeframe": "day", "price_adjustment": "vendor_unverified"},
        {"timeframe": "m15"},
        {"timeframe": "m15", "market_scope": "HK", "price_adjustment": "vendor_unverified"},
        {"market_scope": "US", "price_adjustment": "hfq"},
    ],
)
def test_invalid_inputs(client, changes):
    assert client.post(URL, headers=TOKEN, json={**BODY, **changes}).status_code == 422
    assert client.get(URL, headers=TOKEN).json()["items"] == []


@pytest.mark.parametrize("field", list(BODY))
def test_required_fields(client, field):
    body = {key: value for key, value in BODY.items() if key != field}
    assert client.post(URL, headers=TOKEN, json=body).status_code == 422


@pytest.mark.parametrize(
    "changes",
    [
        {"price_adjustment": "qfq"},
        {"price_adjustment": "hfq"},
        {"market_scope": "HK", "price_adjustment": "hfq"},
        {"market_scope": "CN", "price_adjustment": "hfq"},
        {"market_scope": "US", "price_adjustment": "qfq"},
        {"timeframe": "m15", "market_scope": "CN", "price_adjustment": "vendor_unverified"},
    ],
)
def test_valid_scopes(client, changes):
    result = create(client, **changes)
    assert result["algorithm_version"] == ("m15-v1" if result["timeframe"] == "m15" else "daily-v1")


@pytest.mark.parametrize(
    "first,second",
    [("Test", "test"), ("ＡＢＣ", "abc"), ("Café", "Cafe\u0301"), ("Straße", "STRASSE")],
)
def test_normalized_name_unique(client, first, second):
    saved = create(client, name=first)
    conflict = client.post(URL, headers=TOKEN, json={**BODY, "name": second})
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "PROFILE_NAME_CONFLICT"
    different = create(client, name="不同名称")
    assert different["parameter_hash"] == saved["parameter_hash"]
    assert len(client.get(URL, headers=TOKEN).json()["items"]) == 2


def test_versions_conflict_atomicity_and_validation(client):
    first = create(client)
    create(client, name="占用名称")
    path = f"{URL}/{first['id']}"
    duplicate = client.put(path, headers=TOKEN, json={**BODY, "name": "占用名称", "version": 1})
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "PROFILE_NAME_CONFLICT"
    assert client.get(path, headers=TOKEN).json() == first
    for value in (True, "1", 1.0, 0, -1):
        assert client.put(path, headers=TOKEN, json={**BODY, "version": value}).status_code == 422
    assert client.delete(path, headers=TOKEN).status_code == 422
    assert client.delete(path, headers=TOKEN, params={"version": 0}).status_code == 422
    updated = client.put(path, headers=TOKEN, json={**BODY, "version": 1}).json()
    for response in (
        client.put(path, headers=TOKEN, json={**BODY, "version": 1}),
        client.delete(path, headers=TOKEN, params={"version": 1}),
    ):
        assert response.status_code == 409
        assert response.json()["code"] == "PROFILE_VERSION_CONFLICT"
    assert client.get(path, headers=TOKEN).json() == updated
    for method in ("get", "put", "delete"):
        kwargs = {"json": {**BODY, "version": 1}} if method == "put" else {}
        for identifier, status in (("bad-id", 422), (str(uuid4()), 404)):
            response = client.request(
                method, f"{URL}/{identifier}?version=1", headers=TOKEN, **kwargs
            )
            assert response.status_code == status, response.text


@pytest.mark.parametrize("method", ["put", "delete"])
def test_concurrent_same_version(client, method):
    profile = create(client)
    path = f"{URL}/{profile['id']}?version=1"
    barrier = Barrier(2)

    def write(index):
        barrier.wait(timeout=10)
        kwargs = {"json": {**BODY, "name": f"并发{index}", "version": 1}} if method == "put" else {}
        return client.request(method, path, headers=TOKEN, **kwargs)

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(write, range(2)))
    expected = [200, 409] if method == "put" else [204, 404]
    assert sorted(response.status_code for response in responses) == expected
    if method == "put":
        assert client.get(path, headers=TOKEN).json()["version"] == 2


def test_openapi(client):
    schema = client.get("/openapi.json").json()
    for path, methods in (
        (URL, ("get", "post")),
        (URL + "/{profile_id}", ("get", "put", "delete")),
    ):
        for method in methods:
            operation = schema["paths"][path][method]
            assert operation["security"] == [{"HTTPBearer": []}]
            assert {"401", "404", "409", "422", "503"} <= operation["responses"].keys()
    assert set(BODY) == set(schema["components"]["schemas"]["ProfileInput"]["required"])
    assert "201" in schema["paths"][URL]["post"]["responses"]
    parameters = schema["paths"][URL + "/{profile_id}"]["delete"]["parameters"]
    assert next(item for item in parameters if item["name"] == "version")["required"]
    assert "security" not in schema["paths"]["/api/v1/indicators/daily"]["post"]
    assert "security" not in schema["paths"]["/api/v1/indicators/minute"]["post"]


def test_only_name_unique_integrity_errors_are_conflicts():
    def error(original):
        return IntegrityError("statement", {}, original)

    assert name_conflict(
        error(sqlite3.IntegrityError("UNIQUE constraint failed: t_indicator_profile.name_key"))
    )
    assert not name_conflict(
        error(sqlite3.IntegrityError("NOT NULL constraint failed: t_indicator_profile.name"))
    )
    assert not name_conflict(
        error(sqlite3.IntegrityError("UNIQUE constraint failed: t_indicator_profile.id"))
    )
    assert name_conflict(
        error(Exception(1062, "Duplicate entry for key 'uq_indicator_profile_name_key'"))
    )
    assert not name_conflict(error(Exception(1452, "foreign key constraint failed")))
