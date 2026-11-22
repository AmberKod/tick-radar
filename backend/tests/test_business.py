import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import delete, event
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import create_async_engine

from cross_market.apps.api.main import create_app
from cross_market.modules.securities.infrastructure.models import Security
from cross_market.modules.watchlist.infrastructure.models import WatchlistGroup, WatchlistItem
from cross_market.shared.config import Settings

ROOT = Path(__file__).resolve().parents[1]
TOKEN = {"Authorization": "Bearer test-token"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    url = f"sqlite+aiosqlite:///{tmp_path / 'business.db'}"
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["connection_url"] = url
    command.upgrade(config, "head")

    def engine_factory(settings):
        engine = create_async_engine(url)

        @event.listens_for(engine.sync_engine, "connect")
        def foreign_keys(connection, record):
            connection.execute("PRAGMA foreign_keys=ON")

        return engine

    monkeypatch.setattr("cross_market.apps.api.main.create_engine", engine_factory)
    app = create_app(Settings(api_token="test-token"))
    with TestClient(app) as value:
        yield value


def test_from_quote_register_duplicate_and_validation(client):
    from datetime import UTC, datetime

    from cross_market.modules.market_data.application.schemas import QuoteDTO, QuotesResponse

    quote = QuoteDTO(
        symbol="US:AAPL",
        market="US",
        currency="USD",
        provider_symbol="usAAPL",
        name="供应商名称",
        price="12.30",
        received_at=datetime.now(UTC),
    )
    client.app.state.quote_service = SimpleNamespace(
        get_quotes=AsyncMock(
            return_value=QuotesResponse(quotes=[quote], checked_at=datetime.now(UTC))
        )
    )
    body = {"symbol": "US:AAPL", "exchange": "NASDAQ"}
    first = client.post("/api/v1/securities/from-quote", headers=TOKEN, json=body)
    assert first.status_code == 201, first.text
    assert first.json()["source"] == "TENCENT_LOOKUP"
    assert first.json()["name"] == "供应商名称"
    duplicate = client.post("/api/v1/securities/from-quote", headers=TOKEN, json=body)
    assert duplicate.status_code == 201, duplicate.text
    assert duplicate.json() == first.json()
    for changes in ({"exchange": "NYSE"}, {"security_type": "ETF"}):
        conflict = client.post(
            "/api/v1/securities/from-quote", headers=TOKEN, json={**body, **changes}
        )
        assert conflict.status_code == 409, conflict.text
        assert conflict.json()["code"] == "SECURITY_IDENTITY_CONFLICT"
    assert client.get("/api/v1/securities", headers=TOKEN).json()["items"] == [first.json()]
    assert (
        client.post(
            "/api/v1/securities/from-quote", headers=TOKEN, json={"symbol": "US:AAPL"}
        ).status_code
        == 422
    )
    assert client.post("/api/v1/securities/from-quote", json=body).status_code == 401
    quote.price = None
    assert client.post("/api/v1/securities/from-quote", headers=TOKEN, json=body).status_code == 422


@pytest.mark.parametrize(
    ("ticker", "exchange", "wrong_exchange"),
    [
        ("AAPL.OQ", "NASDAQ", "NYSE"),
        ("AAPL.N", "NYSE", "AMEX"),
        ("AAPL.A", "AMEX", "NASDAQ"),
        ("AAPL", "NASDAQ", None),
    ],
)
async def test_from_quote_provider_exchange_http(client, ticker, exchange, wrong_exchange):
    import fakeredis.aioredis
    import httpx

    from cross_market.modules.market_data.application.service import QuoteService

    payload = f'v_usAAPL="200~供应商名称~{ticker}~12.30~12.00";'
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=payload.encode("gb18030"))
        )
    ) as http:
        client.app.state.quote_service = QuoteService(
            http, fakeredis.aioredis.FakeRedis(), Settings()
        )
        body = {"symbol": "US:AAPL", "exchange": exchange}
        missing = client.post(
            "/api/v1/securities/from-quote", headers=TOKEN, json={"symbol": "US:AAPL"}
        )
        assert missing.status_code == 422
        if wrong_exchange:
            mismatch = client.post(
                "/api/v1/securities/from-quote",
                headers=TOKEN,
                json={**body, "exchange": wrong_exchange},
            )
            assert mismatch.status_code == 422, mismatch.text
            assert mismatch.json()["code"] == "QUOTE_EXCHANGE_MISMATCH"
            assert client.get("/api/v1/securities", headers=TOKEN).json()["total"] == 0
        first = client.post("/api/v1/securities/from-quote", headers=TOKEN, json=body)
        assert first.status_code == 201, first.text
        assert first.json()["exchange"] == exchange
        repeated = client.post("/api/v1/securities/from-quote", headers=TOKEN, json=body)
        assert repeated.status_code == 201, repeated.text
        assert repeated.json() == first.json()
        conflict = client.post(
            "/api/v1/securities/from-quote",
            headers=TOKEN,
            json={**body, "security_type": "ETF"},
        )
        assert conflict.status_code == 409, conflict.text
        assert conflict.json()["code"] == "SECURITY_IDENTITY_CONFLICT"
        assert client.get("/api/v1/securities", headers=TOKEN).json()["items"] == [first.json()]


def security(client, symbol="US:AAPL", exchange="NASDAQ"):
    response = client.post(
        "/api/v1/securities",
        headers=TOKEN,
        json={"symbol": symbol, "exchange": exchange, "security_type": "STOCK", "name": symbol},
    )
    assert response.status_code == 201, response.text
    return response.json()


def group(client, name):
    response = client.post("/api/v1/watchlist-groups", headers=TOKEN, json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def item(client, group_id, security_id):
    response = client.post(
        "/api/v1/watchlists", headers=TOKEN, json={"group_id": group_id, "security_id": security_id}
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_mysql_lock_namespace_and_release():
    from cross_market.modules.watchlist.infrastructure.locking import lock_watchlist

    keys = []
    for database in ("project_a", "project_b"):
        connection = SimpleNamespace(dialect=SimpleNamespace(name="mysql"))
        session = SimpleNamespace(
            info={},
            connection=AsyncMock(return_value=connection),
            scalar=AsyncMock(side_effect=[database, 1]),
        )
        await lock_watchlist(session)
        await lock_watchlist(session)
        assert session.scalar.await_count == 2
        key = session.scalar.await_args_list[1].args[1]["key"]
        assert len(key) <= 64
        assert database not in key
        keys.append(key)
        release = session.info["connection_finalizers"][0]
        cleanup_connection = SimpleNamespace(scalar=AsyncMock(return_value=1), rollback=AsyncMock())
        await release(cleanup_connection)
        assert cleanup_connection.scalar.await_args.args[1] == {"key": key}
        cleanup_connection.rollback.assert_awaited_once()
    assert keys[0] != keys[1]


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", [0, RuntimeError("release failure")])
async def test_failed_lock_release_invalidates_connection(outcome):
    from cross_market.modules.watchlist.infrastructure.locking import lock_watchlist
    from cross_market.shared.database import get_session
    from cross_market.shared.exceptions import AppError

    connection = SimpleNamespace(
        dialect=SimpleNamespace(name="mysql"),
        scalar=AsyncMock(),
        commit=AsyncMock(),
        invalidate=AsyncMock(),
    )
    if isinstance(outcome, Exception):
        connection.scalar.side_effect = outcome
    else:
        connection.scalar.return_value = outcome
    session = SimpleNamespace(
        info={},
        connection=AsyncMock(return_value=connection),
        scalar=AsyncMock(side_effect=["test_database", 1]),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )
    await lock_watchlist(session)
    connection_context = MagicMock()
    connection_context.__aenter__ = AsyncMock(return_value=connection)
    connection_context.__aexit__ = AsyncMock(return_value=False)
    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=False)
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                engine=SimpleNamespace(connect=lambda: connection_context),
                session_factory=lambda **kwargs: session_context,
            )
        )
    )
    dependency = get_session(request)
    assert await anext(dependency) is session
    with pytest.raises((AppError, RuntimeError)):
        await anext(dependency)
    session.commit.assert_awaited_once()
    connection.invalidate.assert_awaited_once()
    assert "connection_finalizers" not in session.info


def test_auth_fail_closed(client):
    for path in ("securities", "watchlist-groups", "watchlists?group_id=missing", "auth/session"):
        assert client.get(f"/api/v1/{path}").status_code == 401
        assert (
            client.get(f"/api/v1/{path}", headers={"Authorization": "Bearer wrong"}).status_code
            == 401
        )
    assert client.post("/api/v1/securities", json={}).status_code == 401
    assert client.get("/api/v1/auth/session", headers=TOKEN).json() == {"authenticated": True}
    client.app.state.settings = Settings(api_token="")
    response = client.get("/api/v1/securities", headers=TOKEN)
    assert response.status_code == 503
    assert response.json()["code"] == "AUTH_NOT_CONFIGURED"


@pytest.mark.parametrize(
    ("symbol", "exchange"),
    [
        ("CN:600000", "SSE"),
        ("CN:000001", "SZSE"),
        ("CN:300001", "SZSE"),
        ("CN:430001", "BSE"),
        ("CN:830001", "BSE"),
        ("CN:920001", "BSE"),
        ("HK:00700", "HKEX"),
        (" us:brk.b ", " nyse "),
        ("US:BRK-B", "AMEX"),
    ],
)
def test_symbols(client, symbol, exchange):
    row = security(client, symbol, exchange)
    assert row["symbol"] == symbol.strip().upper()
    assert row["source"] == "MANUAL"
    assert row["created_at"].endswith("Z")
    assert "price" not in row


@pytest.mark.parametrize(
    ("symbol", "exchange"),
    [
        ("CN:600000", "SZSE"),
        ("CN:100000", "SSE"),
        ("CN:900001", "BSE"),
        ("HK:700", "HKEX"),
        ("US:AAPL", "HKEX"),
        ("US:A/A", "NASDAQ"),
        ("US:A..B", "NASDAQ"),
    ],
)
def test_invalid_symbols(client, symbol, exchange):
    response = client.post(
        "/api/v1/securities",
        headers=TOKEN,
        json={"symbol": symbol, "exchange": exchange, "security_type": "STOCK", "name": "测试"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_market_filter_and_pagination(client):
    security(client, "CN:600000", "SSE")
    security(client, "HK:00700", "HKEX")
    security(client)
    security(client, "US:MSFT")
    for market, count in (("CN", 1), ("HK", 1), ("US", 2)):
        data = client.get(f"/api/v1/securities?market={market}&page_size=1", headers=TOKEN).json()
        assert data["total"] == count
        assert len(data["items"]) == 1
        assert data["items"][0]["market"] == market
    data = client.get("/api/v1/securities?market=US&q=MSFT", headers=TOKEN).json()
    assert data["total"] == 1
    assert client.get("/api/v1/securities?market=HK&q=MSFT", headers=TOKEN).json()["total"] == 0
    assert client.get("/api/v1/securities?market=EU", headers=TOKEN).status_code == 422


@pytest.mark.parametrize(
    ("method", "path", "body", "status", "code"),
    [
        (
            "get",
            "/api/v1/securities/00000000-0000-0000-0000-000000000001",
            None,
            404,
            "SECURITY_NOT_FOUND",
        ),
        ("get", "/api/v1/securities?page=0", None, 422, "VALIDATION_ERROR"),
        (
            "get",
            "/api/v1/watchlists?group_id=00000000-0000-0000-0000-000000000001",
            None,
            404,
            "GROUP_NOT_FOUND",
        ),
        ("post", "/api/v1/watchlist-groups", {"name": ""}, 422, "VALIDATION_ERROR"),
    ],
)
def test_error_envelope(client, method, path, body, status, code):
    response = client.request(
        method, path, json=body, headers={**TOKEN, "X-Request-ID": "business-trace"}
    )
    assert response.status_code == status
    assert response.json() == {
        "code": code,
        "message": response.json()["message"],
        "trace_id": "business-trace",
        "details": None,
    }
    assert response.headers["X-Request-ID"] == "business-trace"


def test_integrity_error_trace(client):
    group(client, "重复")
    response = client.post(
        "/api/v1/watchlist-groups",
        json={"name": "重复"},
        headers={**TOKEN, "X-Request-ID": "conflict-trace"},
    )
    assert response.status_code == 409
    assert response.json() == {
        "code": "CONFLICT",
        "message": "数据重复或引用冲突",
        "trace_id": "conflict-trace",
        "details": None,
    }


def test_openapi_error_and_enum_contract(client):
    schema = client.app.openapi()
    dto = schema["components"]["schemas"]["SecurityDTO"]["properties"]
    assert dto["id"]["type"] == "string"
    for field in ("market", "exchange", "security_type", "status"):
        assert dto[field]["enum"]
    assert dto["source"]["enum"] == ["MANUAL", "TENCENT_LOOKUP"]
    for path in ("/api/v1/securities", "/api/v1/watchlists"):
        responses = schema["paths"][path]["get"]["responses"]
        for status in ("401", "404", "409", "422", "503"):
            assert responses[status]["content"]["application/json"]["schema"] == {
                "$ref": "#/components/schemas/ErrorResponse"
            }


def test_security_crud_and_rollback(client):
    row = security(client)
    duplicate = client.post(
        "/api/v1/securities",
        headers=TOKEN,
        json={"symbol": "US:AAPL", "exchange": "NASDAQ", "security_type": "ETF", "name": "重复"},
    )
    assert duplicate.status_code == 409
    assert security(client, "US:MSFT")["symbol"] == "US:MSFT"
    path = f"/api/v1/securities/{row['id']}"
    assert client.get(path, headers=TOKEN).json() == row
    assert (
        client.put(path, headers=TOKEN, json={"name": "新名称", "status": "INACTIVE"}).json()[
            "status"
        ]
        == "INACTIVE"
    )
    assert client.put(path, headers=TOKEN, json={"symbol": "US:OTHER"}).status_code == 422
    assert client.put(path, headers=TOKEN, json={"name": None}).status_code == 422
    assert (
        client.get(
            "/api/v1/securities/00000000-0000-0000-0000-000000000001", headers=TOKEN
        ).status_code
        == 404
    )
    page = client.get("/api/v1/securities?q=MSFT&page_size=1", headers=TOKEN).json()
    assert page["total"] == 1 and len(page["items"]) == 1
    assert client.get("/api/v1/securities?page=0", headers=TOKEN).status_code == 422
    assert client.get("/api/v1/securities?page_size=101", headers=TOKEN).status_code == 422


def test_watchlist_crud_sort_and_move(client):
    a, b = group(client, "分组一"), group(client, "分组二")
    s1, s2 = security(client), security(client, "US:MSFT")
    x, y = item(client, a["id"], s1["id"]), item(client, a["id"], s2["id"])
    assert x["security"] == s1
    assert client.delete(f"/api/v1/watchlist-groups/{a['id']}", headers=TOKEN).status_code == 409
    assert (
        client.post("/api/v1/watchlist-groups", headers=TOKEN, json={"name": "分组一"}).status_code
        == 409
    )
    assert (
        client.post(
            "/api/v1/watchlists", headers=TOKEN, json={"group_id": a["id"], "security_id": s1["id"]}
        ).status_code
        == 409
    )
    assert (
        client.put(f"/api/v1/watchlists/{x['id']}", headers=TOKEN, json={"note": "备注"}).json()[
            "note"
        ]
        == "备注"
    )
    for ids in ([x["id"]], [x["id"], x["id"]], [x["id"], "missing"]):
        response = client.put(
            "/api/v1/watchlists/order", headers=TOKEN, json={"group_id": a["id"], "ids": ids}
        )
        assert response.status_code == 422
    ordered = client.put(
        "/api/v1/watchlists/order",
        headers=TOKEN,
        json={"group_id": a["id"], "ids": [y["id"], x["id"]]},
    ).json()["items"]
    assert [row["id"] for row in ordered] == [y["id"], x["id"]]
    assert [row["position"] for row in ordered] == [0, 1]
    assert (
        client.put(
            "/api/v1/watchlist-groups/order", headers=TOKEN, json={"ids": [a["id"]]}
        ).status_code
        == 422
    )
    assert (
        client.put(
            "/api/v1/watchlist-groups/order", headers=TOKEN, json={"ids": [b["id"], a["id"]]}
        ).json()["groups"][0]["id"]
        == b["id"]
    )
    assert (
        client.post(
            f"/api/v1/watchlists/{x['id']}/move",
            headers=TOKEN,
            json={"group_id": b["id"], "position": 1},
        ).status_code
        == 422
    )
    moved = client.post(
        f"/api/v1/watchlists/{x['id']}/move",
        headers=TOKEN,
        json={"group_id": b["id"], "position": 0},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["position"] == 0
    assert (
        client.get(f"/api/v1/watchlists?group_id={a['id']}", headers=TOKEN).json()["items"][0][
            "position"
        ]
        == 0
    )
    assert client.delete(f"/api/v1/watchlists/{x['id']}", headers=TOKEN).status_code == 204
    assert client.delete(f"/api/v1/watchlist-groups/{b['id']}", headers=TOKEN).status_code == 204
    assert (
        client.get("/api/v1/watchlist-groups", headers=TOKEN).json()["groups"][0]["position"] == 0
    )
    assert (
        client.get(
            "/api/v1/watchlists?group_id=00000000-0000-0000-0000-000000000001", headers=TOKEN
        ).status_code
        == 404
    )


def test_foreign_keys_and_capacity(client):
    a = group(client, "a")
    s = security(client)
    item(client, a["id"], s["id"])

    async def verify():
        async with client.app.state.session_factory() as session:
            with pytest.raises(IntegrityError):
                await session.execute(delete(Security).where(Security.id == s["id"]))
            await session.rollback()
            # 绕过 API 注入容量边界，数据库仍强制证券外键和唯一约束。
            for number in range(499):
                security_row = Security(
                    symbol=f"US:TEST{number}",
                    market="US",
                    exchange="NASDAQ",
                    security_type="STOCK",
                    name="容量测试",
                    currency="USD",
                )
                session.add(security_row)
                await session.flush()
                session.add(
                    WatchlistItem(
                        group_id=a["id"], security_id=security_row.id, position=number + 1, note=""
                    )
                )
            session.add_all(
                [
                    WatchlistGroup(name=f"group-{number}", position=number + 1)
                    for number in range(49)
                ]
            )
            await session.commit()
            with pytest.raises(IntegrityError):
                session.add(WatchlistItem(group_id=a["id"], security_id="missing", position=500))
                await session.flush()
            await session.rollback()

    asyncio.run(verify())
    extra = security(client, "US:EXTRA")
    assert (
        client.post(
            "/api/v1/watchlists",
            headers=TOKEN,
            json={"group_id": a["id"], "security_id": extra["id"]},
        ).status_code
        == 409
    )
    assert (
        len(client.get(f"/api/v1/watchlists?group_id={a['id']}", headers=TOKEN).json()["items"])
        == 500
    )
    assert (
        client.post(
            "/api/v1/watchlist-groups", headers=TOKEN, json={"name": "overflow"}
        ).status_code
        == 409
    )


@pytest.mark.parametrize(("symbol", "exchange"), [("CN:510300", "SSE"), ("CN:159915", "SZSE")])
def test_etf_identity_uses_type_specific_prefix(client, symbol, exchange):
    response = client.post(
        "/api/v1/securities",
        headers=TOKEN,
        json={
            "symbol": symbol,
            "exchange": exchange,
            "security_type": "ETF",
            "name": "合成ETF资料",
        },
    )
    assert response.status_code == 201
    assert response.json()["security_type"] == "ETF"


def test_uuid_inputs_are_canonical_before_query_and_order(client):
    a, b = group(client, "规范化一"), group(client, "规范化二")
    s = security(client)
    x = item(client, a["id"].upper(), s["id"].upper())
    assert x["group_id"] == a["id"] and x["security_id"] == s["id"]
    ordered = client.put(
        "/api/v1/watchlist-groups/order",
        headers=TOKEN,
        json={
            "ids": [b["id"].upper(), a["id"].upper()],
        },
    )
    assert ordered.status_code == 200
    assert ordered.json()["groups"][0]["id"] == b["id"]
    moved = client.post(
        f"/api/v1/watchlists/{x['id'].upper()}/move",
        headers=TOKEN,
        json={"group_id": b["id"].upper()},
    )
    assert moved.status_code == 200 and moved.json()["group_id"] == b["id"]
    missing = client.get(f"/api/v1/securities/{uuid4()}", headers=TOKEN)
    assert missing.status_code == 404
    assert client.get("/api/v1/securities/not-a-uuid", headers=TOKEN).status_code == 422


async def test_cancelled_write_rolls_back_before_connection_finalizer():
    from cross_market.shared.database import get_session

    events = []

    async def rollback():
        events.append("rollback")

    async def finalize(_connection):
        events.append("release")

    connection = SimpleNamespace(invalidate=AsyncMock())
    session = SimpleNamespace(
        info={"connection_finalizers": [finalize]}, commit=AsyncMock(), rollback=rollback
    )
    connection_context, session_context = MagicMock(), MagicMock()
    connection_context.__aenter__ = AsyncMock(return_value=connection)
    connection_context.__aexit__ = AsyncMock(return_value=False)
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=False)
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                engine=SimpleNamespace(connect=lambda: connection_context),
                session_factory=lambda **kwargs: session_context,
            )
        )
    )
    dependency = get_session(request)
    assert await anext(dependency) is session
    with pytest.raises(asyncio.CancelledError):
        await dependency.athrow(asyncio.CancelledError())
    assert events == ["rollback", "release"]
    session.commit.assert_not_awaited()


def test_database_failure_and_rollback(client, monkeypatch):
    factory = client.app.state.session_factory

    class FailingSession(factory.class_):
        async def commit(self):
            raise OperationalError("hidden credentials", {}, Exception("hidden password"))

    from sqlalchemy.ext.asyncio import async_sessionmaker

    client.app.state.session_factory = async_sessionmaker(
        client.app.state.engine, class_=FailingSession, expire_on_commit=False
    )
    response = client.post(
        "/api/v1/securities",
        headers=TOKEN,
        json={"symbol": "US:FAIL", "exchange": "NASDAQ", "security_type": "STOCK", "name": "回滚"},
    )
    assert response.status_code == 503
    assert response.json() == {
        "code": "DATABASE_UNAVAILABLE",
        "message": "数据库暂不可用",
        "trace_id": response.headers["X-Request-ID"],
        "details": None,
    }
    client.app.state.session_factory = factory
    assert client.get("/api/v1/securities", headers=TOKEN).json()["total"] == 0


def test_concurrent_group_writes(client):
    def create(number):
        return client.post(
            "/api/v1/watchlist-groups", headers=TOKEN, json={"name": f"并发-{number}"}
        )

    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(pool.map(create, range(12)))
    assert all(response.status_code == 201 for response in responses)
    rows = client.get("/api/v1/watchlist-groups", headers=TOKEN).json()["groups"]
    assert [row["position"] for row in rows] == list(range(12))
    assert len({row["id"] for row in rows}) == 12


def test_move_duplicate_rollback(client):
    a, b = group(client, "a"), group(client, "b")
    s = security(client)
    x = item(client, a["id"], s["id"])
    item(client, b["id"], s["id"])
    assert (
        client.post(
            f"/api/v1/watchlists/{x['id']}/move", headers=TOKEN, json={"group_id": b["id"]}
        ).status_code
        == 409
    )
    assert (
        client.get(f"/api/v1/watchlists?group_id={a['id']}", headers=TOKEN).json()["items"][0]["id"]
        == x["id"]
    )
