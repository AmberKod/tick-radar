import sqlite3
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError
from test_portfolio import TOKEN, URL, accepted, account, post
from test_portfolio import client as portfolio_client  # noqa: F401

from cross_market.modules.portfolio.application.transfer_schemas import PortfolioTransferCreate
from cross_market.modules.portfolio.domain.replay import Fact, replay
from cross_market.modules.portfolio.domain.transfers import implied_rate

TRANSFERS = "/api/v1/portfolio/transfers"


@pytest.fixture
def transfer_client(portfolio_client):  # noqa: F811
    return portfolio_client


def body(source, target, **values):
    return {
        "request_id": str(uuid4()),
        "source_account_id": source,
        "target_account_id": target,
        "occurred_at": "2026-01-02T00:00:00Z",
        "source_amount": "100",
        "target_amount": "100",
        **values,
    }


def setup_pair(client, currency="CNY"):
    source, target = account(client)["id"], account(client, currency)["id"]
    accepted(post(client, source, "DEPOSIT", amount="1000"))
    return source, target


def create(client, payload):
    return client.post(TRANSFERS, headers=TOKEN, json=payload)


def summary(client, owner):
    return client.get(f"{URL}/{owner}/summary", headers=TOKEN).json()


def test_domain_cash_and_rate():
    d = Decimal
    result = replay(
        [Fact("DEPOSIT", amount=d(1000)), Fact("TRANSFER_OUT", amount=d(100), fee=d(2))]
    )
    assert (
        result.cash_balance,
        result.internal_net_flow,
        result.external_net_flow,
        result.standalone_fees,
    ) == (d(898), d(-100), d(1000), d(2))
    result = replay([Fact("TRANSFER_IN", amount=d(100))])
    assert (result.cash_balance, result.internal_net_flow, result.external_net_flow) == (
        d(100),
        d(100),
        d(0),
    )
    assert implied_rate("3", "1") == "0.333333333333"
    assert implied_rate("1000000000000", "1.0000005") == "0.000000000001"


@pytest.mark.parametrize(
    "changes",
    [
        {"source_amount": 1},
        {"source_amount": "0"},
        {"target_amount": "0"},
        {"source_fee": "-1"},
        {"source_amount": "1e2"},
        {"target_amount": "1.000000001"},
        {"source_amount": "10000000000000000"},
        {"note": 1},
        {"note": "x" * 501},
        {"occurred_at": "1899-12-31T00:00:00Z"},
        {"occurred_at": "2099-01-01T00:00:00Z"},
        {"occurred_at": "2026-01-01T00:00:00"},
    ],
)
def test_schema_rejects_invalid(changes):
    with pytest.raises(ValidationError):
        PortfolioTransferCreate.model_validate(body(str(uuid4()), str(uuid4()), **changes))


def test_create_freezes_actual_amounts_and_names(transfer_client):
    client = transfer_client
    source, target = setup_pair(client, "USD")
    payload = body(source, target, source_amount="300", target_amount="41.13", source_fee="2")
    result = accepted(create(client, payload))
    assert result["implied_rate"] == "0.137100000000"
    assert result["rate_basis"] == "ACTUAL_AMOUNTS"
    assert result["source_amount"] == "300.00000000"
    assert result["target_amount"] == "41.13000000"
    assert summary(client, source)["cash_balance"] == "698.00000000"
    assert summary(client, target)["cash_balance"] == "41.13000000"
    assert summary(client, source)["external_net_flow"] == "1000.00000000"
    assert accepted(create(client, {**payload, "source_amount": "300.00000000"})) == result
    assert create(client, {**payload, "target_amount": "41"}).json()["code"] == (
        "IDEMPOTENCY_CONFLICT"
    )
    client.put(f"{URL}/{source}", headers=TOKEN, json={"name": "改名", "is_active": False})
    assert accepted(create(client, payload)) == result
    assert client.get(f"{TRANSFERS}/{result['id']}", headers=TOKEN).json() == result
    page = client.get(TRANSFERS, headers=TOKEN, params={"account_id": target}).json()
    assert page["total"] == 1 and page["items"] == [result]
    ledger = client.get(f"{URL}/{source}/ledger", headers=TOKEN).json()
    outgoing = next(row for row in ledger["items"] if row["id"] == result["source_entry_id"])
    assert outgoing["sequence"] == 2 and outgoing["transfer_id"] == result["id"]
    assert outgoing["cash_delta"] == "-302.00000000"


def test_whole_reverse_and_single_side_rejected(transfer_client):
    client = transfer_client
    source, target = setup_pair(client)
    payload = body(source, target, source_fee="2")
    result = accepted(create(client, payload))
    response = client.post(
        f"{URL}/{source}/entries/{result['source_entry_id']}/reverse",
        headers=TOKEN,
        json={"request_id": str(uuid4()), "reason": "测试"},
    )
    assert response.json()["code"] == "TRANSFER_REVERSAL_REQUIRED"
    request = {"request_id": str(uuid4()), "reason": "整笔撤销"}
    path = f"{TRANSFERS}/{result['id']}/reverse"
    reversed_row = client.post(path, headers=TOKEN, json=request)
    assert reversed_row.status_code == 200, reversed_row.text
    reversed_row = reversed_row.json()
    assert reversed_row["status"] == "REVERSED"
    assert reversed_row["source_reversal_entry_id"]
    assert reversed_row["target_reversal_entry_id"]
    assert client.post(path, headers=TOKEN, json=request).json() == reversed_row
    assert (
        client.post(path, headers=TOKEN, json={**request, "reason": "不同内容"}).json()["code"]
        == "IDEMPOTENCY_CONFLICT"
    )
    assert (
        client.post(path, headers=TOKEN, json={**request, "request_id": str(uuid4())}).json()[
            "code"
        ]
        == "TRANSFER_ALREADY_REVERSED"
    )
    assert summary(client, source)["cash_balance"] == "1000.00000000"
    assert summary(client, target)["cash_balance"] == "0.00000000"
    assert accepted(create(client, payload))["status"] == "REVERSED"


def test_replay_failure_rolls_back_both_sides(transfer_client):
    client = transfer_client
    source, target = setup_pair(client)
    invalid = body(source, target, source_amount="1001", target_amount="1001")
    assert create(client, invalid).json()["code"] == "LEDGER_REPLAY_INVALID"
    historical = body(source, target, occurred_at="2025-01-01T00:00:00Z")
    assert create(client, historical).json()["code"] == "LEDGER_REPLAY_INVALID"
    assert summary(client, source)["entry_count"] == 1
    assert summary(client, target)["entry_count"] == 0
    result = accepted(create(client, body(source, target)))
    accepted(post(client, target, "WITHDRAWAL", amount="100", occurred_at="2026-01-03T00:00:00Z"))
    response = client.post(
        f"{TRANSFERS}/{result['id']}/reverse",
        headers=TOKEN,
        json={"request_id": str(uuid4()), "reason": "已花费"},
    )
    assert response.json()["code"] == "LEDGER_REPLAY_INVALID"
    assert client.get(f"{TRANSFERS}/{result['id']}", headers=TOKEN).json()["status"] == "ACTIVE"
    assert summary(client, source)["cash_balance"] == "900.00000000"
    with sqlite3.connect(client.app.state.engine.url.database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM t_portfolio_transfer").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM t_cash_transaction").fetchone()[0] == 4


def test_http_boundaries_and_ledger_request_collision(transfer_client):
    client = transfer_client
    source, target = setup_pair(client)
    payload = body(source, target)
    assert client.post(TRANSFERS, json=payload).status_code == 401
    assert create(client, {**payload, "target_account_id": source}).status_code == 422
    assert create(client, {**payload, "target_amount": "99"}).json()["code"] == (
        "TRANSFER_AMOUNT_MISMATCH"
    )
    assert create(client, {**payload, "target_account_id": str(uuid4())}).status_code == 404
    assert client.get(f"{TRANSFERS}/{uuid4()}", headers=TOKEN).status_code == 404
    assert client.get(TRANSFERS, headers=TOKEN, params={"page_size": 101}).status_code == 422
    accepted(post(client, target, "DEPOSIT", amount="10", request_id=payload["request_id"]))
    assert create(client, payload).json()["code"] == "IDEMPOTENCY_CONFLICT"
    assert summary(client, source)["entry_count"] == 1


def test_concurrent_same_whole_reversal_returns_one_audit_pair(transfer_client):
    client = transfer_client
    source, target = setup_pair(client)
    result = accepted(create(client, body(source, target)))
    path = f"{TRANSFERS}/{result['id']}/reverse"
    request = {"request_id": str(uuid4()), "reason": "同一整体冲正并发重试"}
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(
            executor.map(lambda _: client.post(path, headers=TOKEN, json=request), range(2))
        )
    assert [response.status_code for response in responses] == [200, 200]
    assert responses[0].json() == responses[1].json()
    assert summary(client, source)["cash_balance"] == "1000.00000000"
    assert summary(client, target)["cash_balance"] == "0.00000000"
    assert summary(client, source)["entry_count"] == 3
    assert summary(client, target)["entry_count"] == 2


def test_concurrent_double_spend_only_one_transfer(transfer_client):
    client = transfer_client
    source, target = setup_pair(client)
    other = account(client)["id"]
    payloads = [
        body(source, receiver, source_amount="700", target_amount="700")
        for receiver in (target, other)
    ]
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda payload: create(client, payload), payloads))
    assert sorted(response.status_code for response in responses) == [201, 409]
    assert summary(client, source)["cash_balance"] == "300.00000000"


def test_global_request_ids_across_disjoint_pairs(transfer_client):
    client = transfer_client
    first_source, first_target = setup_pair(client)
    second_source, second_target = setup_pair(client)
    request_id = str(uuid4())
    first = accepted(create(client, body(first_source, first_target, request_id=request_id)))
    response = create(client, body(second_source, second_target, request_id=request_id))
    assert response.status_code == 409
    assert response.json()["code"] == "IDEMPOTENCY_CONFLICT"
    reverse_id = str(uuid4())
    second = accepted(create(client, body(second_source, second_target)))
    response = client.post(
        f"{TRANSFERS}/{first['id']}/reverse",
        headers=TOKEN,
        json={"request_id": reverse_id, "reason": "撤销第一笔"},
    )
    assert response.status_code == 200
    response = client.post(
        f"{TRANSFERS}/{second['id']}/reverse",
        headers=TOKEN,
        json={"request_id": reverse_id, "reason": "撤销第二笔"},
    )
    assert response.json()["code"] == "IDEMPOTENCY_CONFLICT"
    assert summary(client, second_source)["cash_balance"] == "900.00000000"


def test_fixed_account_lock_order_and_reverse(transfer_client, monkeypatch):
    from cross_market.modules.portfolio.application import transfers

    client = transfer_client
    source, target = setup_pair(client)
    calls = []
    original = transfers.account

    async def recording(session, account_id, **kwargs):
        if kwargs.get("lock"):
            calls.append(account_id)
        return await original(session, account_id, **kwargs)

    monkeypatch.setattr(transfers, "account", recording)
    row = accepted(create(client, body(source, target)))
    assert calls == sorted((source, target))
    calls.clear()
    response = client.post(
        f"{TRANSFERS}/{row['id']}/reverse",
        headers=TOKEN,
        json={"request_id": str(uuid4()), "reason": "验证锁顺序"},
    )
    assert response.status_code == 200
    assert calls == sorted((source, target))


def test_concurrent_opposite_direction(transfer_client):
    client = transfer_client
    source, target = setup_pair(client)
    accepted(post(client, target, "DEPOSIT", amount="1000"))
    payloads = [body(source, target), body(target, source)]
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda payload: create(client, payload), payloads))
    assert [response.status_code for response in responses] == [201, 201]
    assert summary(client, source)["cash_balance"] == "1000.00000000"
    assert summary(client, target)["cash_balance"] == "1000.00000000"


def test_failure_after_first_side_projection_is_atomic(transfer_client, monkeypatch):
    from cross_market.modules.portfolio.application import transfers
    from cross_market.shared.exceptions import AppError

    client = transfer_client
    source, target = setup_pair(client)
    original = transfers.rebuild
    calls = []

    async def fail_second(session, account_id, rows):
        calls.append(account_id)
        if len(calls) == 2:
            raise AppError(503, "TEST_STORAGE_UNAVAILABLE", "模拟第二边写入失败")
        return await original(session, account_id, rows)

    monkeypatch.setattr(transfers, "rebuild", fail_second)
    payload = body(source, target)
    assert create(client, payload).status_code == 503
    assert summary(client, source)["entry_count"] == 1
    assert summary(client, target)["entry_count"] == 0
    assert client.get(TRANSFERS, headers=TOKEN).json()["total"] == 0
    monkeypatch.setattr(transfers, "rebuild", original)
    accepted(create(client, payload))
