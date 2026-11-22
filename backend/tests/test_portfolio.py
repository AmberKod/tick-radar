import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine

from cross_market.apps.api.main import create_app
from cross_market.modules.portfolio.domain.replay import Fact, ReplayError, replay
from cross_market.shared.config import Settings

ROOT = Path(__file__).resolve().parents[1]
URL = "/api/v1/portfolio/accounts"
TOKEN = {"Authorization": "Bearer test-token"}
TIME = "2026-01-01T10:00:00.123456Z"


@pytest.fixture
def client(tmp_path, monkeypatch):
    url = f"sqlite+aiosqlite:///{tmp_path / 'portfolio.db'}"
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["connection_url"] = url
    command.upgrade(config, "head")
    monkeypatch.setattr(
        "cross_market.apps.api.main.create_engine", lambda settings: create_async_engine(url)
    )
    with TestClient(create_app(Settings(api_token="test-token"))) as value:
        yield value


def account(client, currency="CNY"):
    response = client.post(URL, headers=TOKEN, json={"name": str(uuid4()), "currency": currency})
    assert response.status_code == 201, response.text
    return response.json()


def security(client, symbol="CN:600519", exchange="SSE"):
    response = client.post(
        "/api/v1/securities",
        headers=TOKEN,
        json={"symbol": symbol, "exchange": exchange, "security_type": "STOCK", "name": "测试证券"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def post(client, owner, kind, **values):
    return client.post(
        f"{URL}/{owner}/entries",
        headers=TOKEN,
        json={"request_id": str(uuid4()), "kind": kind, "occurred_at": TIME, **values},
    )


def accepted(response):
    assert response.status_code == 201, response.text
    return response.json()


def test_manual_domain_and_full_exit():
    d = Decimal
    facts = [
        Fact("DEPOSIT", amount=d(10000)),
        Fact("BUY", "s", d(100), d(10), fee=d(5)),
        Fact("BUY", "s", d(100), d(20), fee=d(5)),
        Fact("SELL", "s", d(50), d(30), fee=d(5), tax=d(1)),
        Fact("DIVIDEND", "s", amount=d(100), tax=d(10)),
    ]
    result = replay(facts)
    p = result.positions["s"]
    assert (p.quantity, p.total_cost, p.average_cost, p.realized_pnl) == (
        d(150),
        d("2257.5"),
        d("15.05"),
        d("741.5"),
    )
    assert (result.cash_balance, result.dividend_income) == (d(8574), d(90))
    restored = replay(facts[:3] + facts[4:])
    assert restored.cash_balance == d(7080)
    assert restored.positions["s"].total_cost == d(3010)
    result = replay(facts + [Fact("SELL", "s", d(150), d(20))])
    assert result.positions["s"].total_cost == 0
    with pytest.raises(ReplayError):
        replay([Fact("WITHDRAWAL", amount=d(1))])
    with pytest.raises(ReplayError):
        replay([Fact("SELL", "s", d(1), d(1))])


def test_http_ledger_reversal_restart(client):
    owner = account(client)["id"]
    sid = security(client)
    accepted(post(client, owner, "DEPOSIT", amount="10000"))
    for price in ("10", "20"):
        accepted(post(client, owner, "BUY", security_id=sid, quantity="100", price=price, fee="5"))
    sale = accepted(
        post(client, owner, "SELL", security_id=sid, quantity="50", price="30", fee="5", tax="1")
    )
    accepted(post(client, owner, "DIVIDEND", security_id=sid, amount="100", tax="10"))
    path = f"{URL}/{owner}"
    summary = client.get(path + "/summary", headers=TOKEN).json()
    assert summary["cash_balance"] == "8574.00000000"
    assert summary["positions"][0]["total_cost"] == "2257.50000000"
    assert summary["realized_pnl"] == "741.50000000"
    body = {"request_id": str(uuid4()), "reason": "  撤销成交  "}
    reverse_path = path + f"/entries/{sale['id']}/reverse"
    reversal = accepted(client.post(reverse_path, headers=TOKEN, json=body))
    assert reversal["cash_delta"] == "-1494.00000000"
    assert reversal["note"] == "撤销成交"
    assert accepted(client.post(reverse_path, headers=TOKEN, json=body)) == reversal
    assert (
        client.post(reverse_path, headers=TOKEN, json={**body, "request_id": str(uuid4())}).json()[
            "code"
        ]
        == "ENTRY_ALREADY_REVERSED"
    )
    ledger = client.get(path + "/ledger", headers=TOKEN).json()
    original = next(r for r in ledger["items"] if r["id"] == sale["id"])
    assert original["status"] == "REVERSED"
    assert original["reversed_by_id"] == reversal["id"]
    assert ledger["total"] == 6
    with sqlite3.connect(client.app.state.engine.url.database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM t_cash_transaction").fetchone()[0] == 6
        cash = connection.execute("SELECT cash_delta FROM t_cash_transaction").fetchall()
        assert sum((Decimal(row[0]) for row in cash), Decimal(0)) == Decimal(7080)
        assert connection.execute(
            "SELECT quantity,total_cost FROM t_portfolio_position WHERE account_id=?", (owner,)
        ).fetchone() == ("200.00000000", "3010.00000000")
    summary = client.get(path + "/summary", headers=TOKEN).json()
    assert summary["cash_balance"] == "7080.00000000"
    assert summary["total_cost"] == "3010.00000000"
    assert summary["dividend_income"] == "90.00000000"
    assert client.delete(path, headers=TOKEN).json()["code"] == "ACCOUNT_NOT_EMPTY"
    with TestClient(create_app(Settings(api_token="test-token"))) as restarted:
        assert (
            restarted.get(path + "/summary", headers=TOKEN).json()["cash_balance"]
            == "7080.00000000"
        )


@pytest.mark.parametrize(
    "bad", [1, True, "1e2", "NaN", "Inf", "-1", "1.000000001", "10000000000000000"]
)
def test_strict_decimal(client, bad):
    owner = account(client)["id"]
    assert post(client, owner, "DEPOSIT", amount=bad).status_code == 422


def test_atomic_backdate_and_reversal_failure(client):
    owner = account(client)["id"]
    deposit = accepted(post(client, owner, "DEPOSIT", amount="100"))
    accepted(post(client, owner, "WITHDRAWAL", amount="90"))
    invalid = post(client, owner, "WITHDRAWAL", amount="1", occurred_at="2025-01-01T00:00:00Z")
    assert invalid.json()["code"] == "LEDGER_REPLAY_INVALID"
    response = client.post(
        f"{URL}/{owner}/entries/{deposit['id']}/reverse",
        headers=TOKEN,
        json={"request_id": str(uuid4()), "reason": "撤销"},
    )
    assert response.json()["code"] == "LEDGER_REPLAY_INVALID"
    result = client.get(f"{URL}/{owner}/ledger", headers=TOKEN).json()
    assert result["total"] == 2
    assert all(row["status"] == "ACTIVE" for row in result["items"])
    assert (
        client.get(f"{URL}/{owner}/summary", headers=TOKEN).json()["cash_balance"] == "10.00000000"
    )


def test_concurrent_idempotency_and_sell(client):
    owner = account(client)["id"]
    sid = security(client)
    request_id = str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: post(client, owner, "DEPOSIT", amount="1000", request_id=request_id),
                range(2),
            )
        )
    assert [r.status_code for r in results] == [201, 201]
    assert results[0].json() == results[1].json()
    assert (
        post(client, owner, "DEPOSIT", amount="1", request_id=request_id).json()["code"]
        == "IDEMPOTENCY_CONFLICT"
    )
    accepted(post(client, owner, "BUY", security_id=sid, quantity="10", price="10"))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: post(client, owner, "SELL", security_id=sid, quantity="7", price="10"),
                range(2),
            )
        )
    assert sorted(r.status_code for r in results) == [201, 409]
    assert (
        client.get(f"{URL}/{owner}/summary", headers=TOKEN).json()["positions"][0]["quantity"]
        == "3.00000000"
    )


@pytest.mark.parametrize(
    "method,suffix",
    [
        ("get", ""),
        ("post", ""),
        ("get", "/id"),
        ("put", "/id"),
        ("delete", "/id"),
        ("get", "/id/ledger"),
        ("get", "/id/summary"),
        ("post", "/id/entries"),
        ("post", "/id/entries/id/reverse"),
    ],
)
def test_auth(client, method, suffix):
    path = URL + suffix.replace("id", str(uuid4()))
    assert client.request(method, path).status_code == 401
    assert client.request(method, path, headers={"Authorization": "Bearer bad"}).status_code == 401


def test_validation_and_account_lifecycle(client):
    owner = account(client)
    path = f"{URL}/{owner['id']}"
    assert client.get(path, headers=TOKEN).json() == owner
    assert (
        client.put(path, headers=TOKEN, json={"name": "更名", "is_active": False}).status_code
        == 200
    )
    assert post(client, owner["id"], "DEPOSIT", amount="1").json()["code"] == "ACCOUNT_INACTIVE"
    assert client.delete(path, headers=TOKEN).status_code == 204
    first = account(client)
    assert (
        client.post(
            URL, headers=TOKEN, json={"name": first["name"].upper(), "currency": "USD"}
        ).status_code
        == 409
    )
    owner = first["id"]
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    assert post(client, owner, "DEPOSIT", amount="1", occurred_at=future).status_code == 422
    assert post(client, owner, "DEPOSIT", amount="1", unknown=1).status_code == 422
    sid = security(client)
    accepted(post(client, owner, "DEPOSIT", amount="100"))
    assert post(client, owner, "BUY", security_id=sid, quantity="0.5", price="1").status_code == 422
    usd = account(client, "USD")["id"]
    assert (
        post(client, usd, "BUY", security_id=sid, quantity="1", price="1").json()["code"]
        == "CURRENCY_MISMATCH"
    )


def test_fractional_rounding_and_range():
    d = Decimal
    facts = [Fact("DEPOSIT", amount=d(100)), Fact("BUY", "s", d(1), d(1))]
    for _ in range(99):
        facts.append(Fact("SELL", "s", d("0.01"), d("1.01")))
    facts.append(Fact("SELL", "s", d("0.01"), d("1.01")))
    result = replay(facts)
    assert result.positions["s"].quantity == 0
    assert result.positions["s"].total_cost == 0
    assert result.realized_pnl == d("0.01")
    with pytest.raises(ReplayError):
        replay([Fact("BUY", "s", d("9999999999999999"), d("9999999999999999"))])


def test_cumulative_quantity_limit():
    with pytest.raises(ReplayError, match="累计持仓数量"):
        replay([
            Fact("DEPOSIT", amount=Decimal("300000000")),
            Fact("BUY", "s", Decimal("9999999999999999"), Decimal("0.00000001")),
            Fact("BUY", "s", Decimal("9999999999999999"), Decimal("0.00000001")),
        ])


def test_us_fractional_fee_and_security_status(client):
    owner = account(client, "USD")["id"]
    sid = security(client, "US:AAPL", "NASDAQ")
    accepted(post(client, owner, "DEPOSIT", amount="100"))
    accepted(post(client, owner, "BUY", security_id=sid, quantity="0.12345678", price="10"))
    accepted(post(client, owner, "FEE", amount="1"))
    summary = client.get(f"{URL}/{owner}/summary", headers=TOKEN).json()
    assert summary["cash_balance"] == "97.76543220"
    assert summary["standalone_fees"] == "1.00000000"
    assert summary["external_net_flow"] == "100.00000000"
    accepted(post(client, owner, "SELL", security_id=sid, quantity="0.12345678", price="11"))
    summary = client.get(f"{URL}/{owner}/summary", headers=TOKEN).json()
    assert summary["positions"][0]["quantity"] == "0.00000000"
    assert summary["positions"][0]["total_cost"] == "0.00000000"
    assert (
        client.put(
            f"/api/v1/securities/{sid}", headers=TOKEN, json={"status": "INACTIVE"}
        ).status_code
        == 200
    )
    assert (
        post(client, owner, "DIVIDEND", security_id=sid, amount="1").json()["code"]
        == "SECURITY_INACTIVE"
    )


def test_money_storage_and_large_values_are_exact():
    from sqlalchemy.dialects import mysql, sqlite

    from cross_market.modules.portfolio.domain.replay import formatted
    from cross_market.modules.portfolio.infrastructure.models import Entry

    assert Entry.__table__.c.cash_delta.type.compile(dialect=mysql.dialect()) == "NUMERIC(32, 8)"
    assert Entry.__table__.c.cash_delta.type.compile(dialect=sqlite.dialect()) == "VARCHAR(34)"
    value = Decimal("123456789012345678901234.12345678")
    assert formatted(value) == "123456789012345678901234.12345678"
    assert formatted(value.copy_negate()) == "-123456789012345678901234.12345678"


def test_closed_positions_are_not_collection_targets(client):
    owner = account(client)["id"]
    sid = security(client)
    accepted(post(client, owner, "DEPOSIT", amount="100"))
    accepted(post(client, owner, "BUY", security_id=sid, quantity="1", price="10"))
    accepted(post(client, owner, "SELL", security_id=sid, quantity="1", price="11"))
    from cross_market.modules.portfolio.application.summary import list_quote_targets

    async def targets():
        async with client.app.state.session_factory() as session:
            return await list_quote_targets(session)

    assert client.portal.call(targets) == []


def test_migration_downgrade_only_portfolio(tmp_path):
    db = tmp_path / "migration.db"
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["connection_url"] = f"sqlite+aiosqlite:///{db}"
    command.upgrade(config, "head")
    command.downgrade(config, "0004")
    with sqlite3.connect(db) as connection:
        tables = {
            r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert "t_security" in tables and "t_indicator_profile" in tables
    assert not tables.intersection(
        {"t_account", "t_portfolio_transaction", "t_cash_transaction", "t_portfolio_position"}
    )
    command.upgrade(config, "head")
