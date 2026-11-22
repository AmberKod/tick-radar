import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cross_market.modules.alerts.application import service
from cross_market.modules.alerts.application.evaluation import evaluate_rules, sample_for
from cross_market.modules.alerts.application.schemas import AlertRuleCreate, AlertRuleUpdate
from cross_market.modules.alerts.domain.engine import Rule, Sample, State, clear_baseline, evaluate
from cross_market.modules.alerts.infrastructure.models import AlertEvent, AlertRule, AlertRuleState
from cross_market.modules.alerts.interfaces.router import router
from cross_market.modules.market_data.application.schemas import QuoteDTO, QuotesResponse
from cross_market.modules.notifications.infrastructure.models import NotificationOutbox
from cross_market.modules.securities.infrastructure.models import Security
from cross_market.shared.config import Settings
from cross_market.shared.exceptions import AppError, register_exception_handlers

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 22, 12, tzinfo=UTC)
SECURITY_ID = str(uuid4())
BODY = dict(
    name="观察",
    security_id=SECURITY_ID,
    rule_type="PRICE_CROSS_UP",
    threshold="10",
    reset_threshold="9",
    enabled=True,
    cooldown_seconds=0,
)


def sample(value, second=0, key=None):
    return Sample(Decimal(value), key or f"{value}-{second}", NOW + timedelta(seconds=second))


def step(rule, state, value, second=0):
    return evaluate(rule, state, sample(value, second), NOW + timedelta(seconds=second))


@pytest.mark.parametrize(
    "kind,start,hit,reset",
    [
        ("PRICE_CROSS_UP", "9", "10", "8"),
        ("PRICE_CROSS_DOWN", "11", "10", "12"),
    ],
)
def test_crossings_reset_equality_and_oscillation(kind, start, hit, reset):
    rule = Rule(kind, Decimal("10"), Decimal(reset), 0)
    first = step(rule, State(), hit)
    assert not first.triggered and first.state.evaluation_status == "BASELINE"
    second = step(rule, first.state, start, 1)
    trigger = step(rule, second.state, hit, 2)
    assert trigger.triggered and trigger.state.trigger_count == 1
    assert not step(rule, trigger.state, hit, 3).triggered
    armed = step(rule, trigger.state, reset, 4)
    assert not armed.triggered and armed.state.phase == "ARMED"
    assert step(rule, armed.state, hit, 5).triggered


def test_cooldown_cross_is_not_deferred_and_gap_breaks_baseline():
    rule = Rule("PRICE_CROSS_UP", Decimal("10"), Decimal("8"), 30)
    state = State(last_triggered_at=NOW - timedelta(seconds=1))
    state = step(rule, state, "9").state
    cooling = step(rule, state, "10", 1)
    assert cooling.state.evaluation_status == "COOLDOWN"
    assert not step(rule, cooling.state, "11", 40).triggered
    assert not step(rule, state, "11", 181).triggered
    broken = evaluate(rule, replace(state, phase="TRIGGERED"), None, NOW)
    assert broken.state.phase == "TRIGGERED" and broken.state.last_value is None
    restored = step(rule, clear_baseline(state), "11", 10)
    assert not restored.triggered


@pytest.mark.parametrize(
    "kind,value,reset", [("DAY_CHANGE_ABOVE", "5", "4"), ("DAY_CHANGE_BELOW", "-5", "-4")]
)
def test_level_first_sample_and_manual_reset_preserves_cooldown(kind, value, reset):
    rule = Rule(kind, Decimal(value), Decimal(reset), 30)
    triggered = step(rule, State(), value)
    assert triggered.triggered
    armed = clear_baseline(triggered.state, phase="ARMED")
    assert not step(rule, armed, value, 1).triggered
    assert step(rule, armed, value, 31).triggered


def test_duplicate_and_old_received_never_replace_baseline():
    rule = Rule("PRICE_CROSS_UP", Decimal("10"), Decimal("9"), 0)
    first = step(rule, State(), "8")
    duplicate = evaluate(rule, first.state, sample("11", 1, "8-0"), NOW + timedelta(seconds=1))
    assert duplicate.state.last_value == "8" and not duplicate.triggered
    old = evaluate(rule, first.state, sample("11", -1), NOW)
    assert old.state == replace(
        first.state,
        checked_at=NOW,
        evaluation_status="OLD_SAMPLE",
        evaluation_reason=old.state.evaluation_reason,
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"threshold": 10},
        {"threshold": "NaN"},
        {"threshold": "1e3"},
        {"threshold": "1.123456789"},
        {"reset_threshold": "10"},
        {"threshold": "0"},
        {"cooldown_seconds": True},
        {"enabled": 1},
        {"name": "a\n"},
        {"name": "\u200b"},
        {"name": " "},
        {"unexpected": 1},
    ],
)
def test_schema_rejects_invalid_inputs(changes):
    with pytest.raises(ValidationError):
        AlertRuleCreate(**{**BODY, **changes})


def quote(price="9", second=0, **changes):
    return QuoteDTO(
        symbol="US:AAPL",
        market="US",
        currency="USD",
        provider_symbol="usAAPL",
        provider_exchange="NASDAQ",
        price=price,
        prev_close="8",
        received_at=NOW + timedelta(seconds=second),
        quality_status="UNKNOWN",
        source_time_raw=str(second),
        **changes,
    )


def test_quote_eligibility_and_decimal_change():
    security = SimpleNamespace(symbol="US:AAPL", market="US", currency="USD", exchange="NASDAQ")
    good = quote("9", change_percent="999")
    result, _ = sample_for(good, security, "DAY_CHANGE_ABOVE", NOW)
    assert result.value == Decimal("12.50000000")
    for changes in (
        {"price": "NaN"},
        {"price": "Infinity"},
        {"prev_close": "0"},
        {"quality_status": "STALE"},
        {"currency": "CNY"},
        {"received_at": None},
        {"received_at": NOW + timedelta(seconds=1)},
        {"received_at": NOW - timedelta(seconds=181)},
    ):
        assert (
            sample_for(good.model_copy(update=changes), security, "DAY_CHANGE_ABOVE", NOW)[0]
            is None
        )
    assert (
        sample_for(
            good.model_copy(update={"quality_status": "MARKET_CLOSED"}),
            security,
            "DAY_CHANGE_ABOVE",
            NOW,
        )[0]
        is not None
    )


@pytest.fixture
async def factory(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'alerts.db'}"
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["connection_url"] = url
    await asyncio.to_thread(command.upgrade, config, "head")
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add(
            Security(
                id=SECURITY_ID,
                symbol="US:AAPL",
                market="US",
                currency="USD",
                exchange="NASDAQ",
                name="Apple",
                security_type="STOCK",
                source="MANUAL",
            )
        )
        await session.commit()
    yield factory
    await engine.dispose()


async def test_evaluation_atomic_events_snapshots_and_archive(factory):
    async with factory() as session:
        created = await service.create_rule(session, AlertRuleCreate(**BODY))
        await session.commit()
        assert await service.list_quote_targets(session) == ["US:AAPL"]
        await session.rollback()
        assert (await evaluate_rules(session, [quote()], NOW))["triggered"] == 0
        await session.commit()
        assert (await evaluate_rules(session, [quote("10", 1)], NOW + timedelta(seconds=1)))[
            "triggered"
        ] == 1
        await session.commit()
        assert (await evaluate_rules(session, [quote("10", 1)], NOW + timedelta(seconds=2)))[
            "triggered"
        ] == 0
        await session.commit()
        event = await session.scalar(select(AlertEvent))
        outbox = await session.scalar(select(NotificationOutbox))
        assert event.outbox_id == outbox.id
        assert event.rule_snapshot["name"] == created.name
        await session.rollback()
        updated = await service.update_rule(
            session, created.id, AlertRuleUpdate(**{**BODY, "name": "新名", "version": 1})
        )
        await session.commit()
        assert updated.state.last_triggered_at is not None and updated.state.trigger_count == 1
        with pytest.raises(AppError) as error:
            await service.reset_rule(session, created.id, 1)
        assert error.value.code == "ALERT_VERSION_CONFLICT"
        await session.rollback()
        await service.delete_rule(session, created.id, 2)
        await session.commit()
        assert (await service.list_rules(session))["items"] == []
        history = await service.list_events(session)
        assert history.total == 1 and history.items[0].rule_name == "观察"


async def test_rollback_removes_event_and_outbox(factory):
    async with factory() as session:
        await service.create_rule(
            session,
            AlertRuleCreate(
                **{
                    **BODY,
                    "rule_type": "DAY_CHANGE_ABOVE",
                    "threshold": "5",
                    "reset_threshold": "4",
                }
            ),
        )
        await session.commit()
        assert (await evaluate_rules(session, [quote()], NOW))["triggered"] == 1
        await session.rollback()
        assert await session.scalar(select(AlertEvent)) is None
        assert await session.scalar(select(NotificationOutbox)) is None
        row = await session.scalar(select(AlertRuleState))
        assert row.trigger_count == 0


async def test_http_contract_preview_auth_and_realtime(factory):
    app = FastAPI()
    app.include_router(router)
    register_exception_handlers(app)
    app.state.settings = Settings(api_token="test-token")
    app.state.engine = factory.kw["bind"]
    app.state.session_factory = factory

    class Quotes:
        async def snapshot(self, symbols):
            now = datetime.now(UTC)
            return QuotesResponse(
                quotes=[quote().model_copy(update={"received_at": now})], checked_at=now
            )

    app.state.quote_service = Quotes()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        path = "/api/v1/alerts/rules"
        assert (await client.get(path)).status_code == 401
        client.headers["Authorization"] = "Bearer test-token"
        denied = await client.post(path, json={**BODY, "mode": "REALTIME"})
        assert denied.status_code == 422 and denied.json()["code"] == "REALTIME_NOT_VERIFIED"
        created = await client.post(path, json={**BODY, "name": "  观察  "})
        assert created.status_code == 201, created.text
        rule = created.json()
        assert rule["name"] == "观察"
        item = f"{path}/{rule['id']}"
        preview = await client.post(f"{item}/preview")
        assert preview.status_code == 200 and preview.json()["status"] == "BASELINE"
        assert (await client.get(item)).json() == rule
        assert (await client.post(f"{item}/reset", json={"version": True})).status_code == 422
        assert (await client.delete(item)).status_code == 422
        reset = await client.post(f"{item}/reset", json={"version": 1})
        assert reset.json()["version"] == 2
        assert (await client.delete(item, params={"version": 1})).status_code == 409
        assert (await client.delete(item, params={"version": 2})).status_code == 204
        assert (await client.get(item)).status_code == 404
        disabled = await client.post(path, json={**BODY, "mode": "REALTIME", "enabled": False})
        assert disabled.status_code == 201 and disabled.json()["mode"] == "REALTIME"


async def test_rule_capacity_is_rejected_instead_of_silently_unscanned(factory):
    async with factory() as session:
        session.add_all([AlertRule(**{**BODY, "name": f"rule-{i}"}, mode="OBSERVATION")
                         for i in range(200)])
        await session.commit()
        with pytest.raises(AppError) as error:
            await service.create_rule(session, AlertRuleCreate(**BODY))
        assert error.value.code == "ALERT_CAPACITY_EXCEEDED"
        await session.rollback()


async def test_concurrent_evaluators_emit_once(factory):
    async with factory() as session:
        await service.create_rule(session, AlertRuleCreate(**BODY))
        await session.commit()
        await evaluate_rules(session, [quote()], NOW)
        await session.commit()

    async def run():
        async with factory() as session:
            result = await evaluate_rules(session, [quote("10", 1)], NOW + timedelta(seconds=1))
            await session.commit()
            return result

    results = await asyncio.gather(run(), run())
    assert sum(result["triggered"] for result in results) == 1
    async with factory() as session:
        assert len(list(await session.scalars(select(AlertEvent)))) == 1
        assert len(list(await session.scalars(select(NotificationOutbox)))) == 1


async def test_same_source_sample_can_trigger_after_automatic_reset(factory):
    async with factory() as session:
        await service.create_rule(session, AlertRuleCreate(**BODY))
        await session.commit()
        for price, second in [("8", 0), ("10", 1), ("8", 2), ("10", 3)]:
            snapshot = quote(price, second).model_copy(update={"source_time_raw": "same-label"})
            await evaluate_rules(session, [snapshot], NOW + timedelta(seconds=second))
            await session.commit()
        logs = list(await session.scalars(select(AlertEvent)))
        assert len(logs) == 2
        assert sorted(log.trigger_number for log in logs) == [1, 2]
        assert (await session.scalar(select(AlertRuleState))).trigger_count == 2
        assert len(list(await session.scalars(select(NotificationOutbox)))) == 2


async def test_invalid_snapshot_breaks_crossing_and_preview_cache_failure(factory):
    async with factory() as session:
        created = await service.create_rule(session, AlertRuleCreate(**BODY))
        await session.commit()
        await evaluate_rules(session, [quote()], NOW)
        await session.commit()
        await evaluate_rules(session, [], NOW + timedelta(seconds=1))
        await session.commit()
        recovered = await evaluate_rules(session, [quote("11", 2)], NOW + timedelta(seconds=2))
        assert recovered["triggered"] == 0
        await session.commit()
        before = await service.get_rule(session, created.id)

        class FailedCache:
            async def snapshot(self, symbols):
                raise ConnectionError("缓存不可用")

        preview = await service.preview_rule(session, created.id, FailedCache())
        assert not preview.eligible and preview.state_after.last_value is None
        assert await service.get_rule(session, created.id) == before
