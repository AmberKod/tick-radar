import asyncio
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cross_market.modules.alerts.application import schedules as service
from cross_market.modules.alerts.application.schedule_schemas import ScheduleCreate, ScheduleUpdate
from cross_market.modules.alerts.domain.schedules import ZONE, Calendar, decide_slot
from cross_market.modules.alerts.infrastructure.schedule_models import (
    AlertSchedule,
    AlertScheduleRun,
)
from cross_market.modules.alerts.interfaces.schedules import router
from cross_market.modules.market_calendar.application.service import CalendarService
from cross_market.modules.notifications.application import service as notifications
from cross_market.modules.notifications.infrastructure.models import (
    InboxMessage,
    NotificationOutbox,
)
from cross_market.shared.exceptions import register_exception_handlers

NOW = datetime(2026, 11, 23, 6, 30, tzinfo=UTC)
BODY = dict(name="尾盘检查", exchange="SSE", times=["14:30"], message="检查清单", enabled=True)
TOKEN = {"Authorization": "Bearer test-token"}
PREFIX = "/api/v1/alerts"
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
async def calendar():
    value = CalendarService()
    await value.warmup()
    return value


@pytest.fixture
async def factory(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'schedules.db'}"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.attributes["connection_url"] = url
    await asyncio.to_thread(command.upgrade, config, "head")
    engine = create_async_engine(url)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def add(factory, **values):
    async with factory() as session, session.begin():
        row = AlertSchedule(
            **{
                **BODY,
                "grace_seconds": 120,
                "created_at": NOW - timedelta(hours=1),
                "updated_at": NOW - timedelta(hours=1),
                **values,
            }
        )
        session.add(row)
        await session.flush()
        return row.id


async def evaluate(factory, calendar, now=NOW):
    async with factory() as session, session.begin():
        return await service.evaluate_schedules(session, calendar, now)


async def count(session, model):
    return await session.scalar(select(func.count()).select_from(model))


@pytest.mark.parametrize(
    "values",
    [
        {"times": ["13:59"]},
        {"times": ["15:00"]},
        {"times": ["14:60"]},
        {"times": ["14:3"]},
        {"times": ["14:30:00"]},
        {"times": []},
        {"times": ["14:30", "14:30"]},
        {"times": [f"14:{i:02d}" for i in range(9)]},
        {"exchange": "HKEX"},
        {"grace_seconds": 29},
        {"grace_seconds": 601},
        {"grace_seconds": True},
        {"enabled": "true"},
        {"name": "a\nb"},
        {"message": "\t"},
        {"timezone": "UTC"},
        {"name": " "},
    ],
)
def test_schedule_strict_input(values):
    with pytest.raises(ValidationError):
        ScheduleCreate(**{**BODY, **values})


def test_sorted_times_default_disabled_and_newline():
    body = ScheduleCreate(
        name="  检查  ", exchange="BSE", times=["14:59", "14:00"], message="第一行\n第二行"
    )
    assert body.times == ["14:00", "14:59"] and not body.enabled and body.name == "检查"


@pytest.mark.parametrize(
    "seconds,expected", [(-1, "WAITING"), (0, "ENQUEUE"), (119, "ENQUEUE"), (120, "MISSED")]
)
def test_exact_window_boundaries(calendar, seconds, expected):
    status = calendar.get_status("SSE", NOW + timedelta(seconds=seconds))
    decision = decide_slot(
        now=NOW + timedelta(seconds=seconds),
        scheduled_at=NOW,
        active_since=NOW - timedelta(hours=1),
        grace_seconds=120,
        calendar=service.primitive(status, "SSE"),
        enabled=True,
    )
    assert decision.status == expected


@pytest.mark.parametrize("seconds", [0, 180])
async def test_unknown_calendar_never_consumes_slot(factory, calendar, seconds):
    sid = await add(factory)
    status = calendar.get_status("SSE", NOW).model_copy(update={"state": "UNKNOWN"})
    unavailable = SimpleNamespace(get_status=lambda *args: status)
    result = await evaluate(factory, unavailable, NOW + timedelta(seconds=seconds))
    assert result["skipped"] == 1 and result["enqueued"] == result["missed"] == 0
    async with factory() as session:
        assert await count(session, AlertScheduleRun) == 0
    if seconds == 0:
        assert (await evaluate(factory, calendar, NOW + timedelta(seconds=1)))["enqueued"] == 1
    else:
        assert (await evaluate(factory, calendar, NOW + timedelta(seconds=181)))["missed"] == 1
    async with factory() as session:
        assert (await service.get_schedule(session, sid)).version == 1


@pytest.mark.parametrize(
    "now",
    [
        datetime(2026, 11, 22, 6, 30, tzinfo=UTC),
        datetime(2026, 10, 1, 6, 30, tzinfo=UTC),
        datetime(2027, 1, 4, 6, 30, tzinfo=UTC),
    ],
)
async def test_non_trading_and_uncovered_never_enqueue(factory, calendar, now):
    await add(factory)
    result = await evaluate(factory, calendar, now)
    assert result["enqueued"] == result["missed"] == 0
    async with factory() as session:
        assert (
            await count(session, AlertScheduleRun) == await count(session, NotificationOutbox) == 0
        )


async def test_manual_closure_and_calendar_failure(factory):
    await add(factory)
    closed = CalendarService({"SSE:2026-11-23": "临时休市"})
    await closed.warmup()
    assert (await evaluate(factory, closed))["enqueued"] == 0

    def fail(*args):
        raise RuntimeError("sensitive")

    result = await evaluate(factory, SimpleNamespace(get_status=fail))
    assert result["skipped"] == 1
    async with factory() as session:
        assert await count(session, AlertScheduleRun) == 0


async def test_once_across_versions_snapshot_and_preview(factory, calendar):
    sid = await add(factory)
    async with factory() as session:
        preview = await service.preview_schedule(session, sid, calendar, NOW)
        assert preview.slots[0].status == "ENQUEUE"
        assert (
            await count(session, AlertScheduleRun) == await count(session, NotificationOutbox) == 0
        )
    assert (await evaluate(factory, calendar))["enqueued"] == 1
    assert (await evaluate(factory, calendar, NOW + timedelta(seconds=1)))["enqueued"] == 0
    async with factory() as session, session.begin():
        await service.update_schedule(
            session,
            sid,
            ScheduleUpdate(**{**BODY, "name": "改名", "grace_seconds": 600}, version=1),
        )
    assert (await evaluate(factory, calendar, NOW + timedelta(seconds=2)))["enqueued"] == 0
    async with factory() as session:
        preview = await service.preview_schedule(session, sid, calendar, NOW + timedelta(seconds=2))
        assert preview.slots[0].expires_at == NOW + timedelta(seconds=120)
        record = await session.scalar(select(AlertScheduleRun))
        assert record.schedule_name == "尾盘检查" and record.schedule_version == 1
        assert record.rule_snapshot["name"] == "尾盘检查"
        assert record.calendar["state"] == "REGULAR_SESSION"
        assert await count(session, NotificationOutbox) == 1


async def test_event_outbox_rollback_and_concurrent_once(factory, calendar):
    await add(factory)
    async with factory() as session:
        assert (await service.evaluate_schedules(session, calendar, NOW))["enqueued"] == 1
        await session.rollback()
    async with factory() as session:
        assert (
            await count(session, AlertScheduleRun) == await count(session, NotificationOutbox) == 0
        )
    results = await asyncio.gather(evaluate(factory, calendar), evaluate(factory, calendar))
    assert sum(r["enqueued"] for r in results) == 1
    async with factory() as session:
        assert (
            await count(session, AlertScheduleRun) == await count(session, NotificationOutbox) == 1
        )


async def test_new_enable_past_slot_missed_and_today_only(factory, calendar):
    sid = await add(factory, updated_at=NOW + timedelta(seconds=1))
    assert (await evaluate(factory, calendar, NOW + timedelta(seconds=2)))["missed"] == 1
    async with factory() as session:
        assert await count(session, NotificationOutbox) == 0
        assert (await session.scalar(select(AlertScheduleRun))).session_date == NOW.astimezone(
            ZONE
        ).date()
    # 下一交易日仅判当天，不回补过去日期。
    next_day = NOW + timedelta(days=1)
    assert (await evaluate(factory, calendar, next_day))["enqueued"] == 1
    async with factory() as session:
        assert await count(session, AlertScheduleRun) == 2
        assert (await service.get_schedule(session, sid)).enabled


async def test_window_delivery_then_expired_not_inbox(factory, calendar):
    await add(factory)
    await evaluate(factory, calendar)
    async with factory() as session, session.begin():
        assert (await notifications.dispatch_pending(session, now=NOW + timedelta(seconds=120)))[
            "sent"
        ] == 0
    async with factory() as session:
        assert (await session.scalar(select(NotificationOutbox))).status == "EXPIRED"
        assert await count(session, InboxMessage) == 0


@pytest.fixture
async def client(factory, calendar):
    app = FastAPI()
    app.state.settings = SimpleNamespace(api_token=SecretStr("test-token"))
    app.state.session_factory = factory
    app.state.engine = factory.kw["bind"]
    app.state.market_calendar = calendar
    register_exception_handlers(app)
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        client.test_app = app
        yield client


async def test_api_versions_soft_archive_preview_readonly(client, factory):
    body = {**BODY, "enabled": False}
    response = await client.post(PREFIX + "/schedules", json=body, headers=TOKEN)
    assert response.status_code == 201, response.text
    row = response.json()
    path = PREFIX + "/schedules/" + row["id"]
    assert row["timezone"] == "Asia/Shanghai" and row["created_at"].endswith("Z")
    updated = await client.put(path, json={**body, "version": 1}, headers=TOKEN)
    assert updated.json()["version"] == 2
    conflict = await client.put(path, json={**body, "version": 1}, headers=TOKEN)
    assert conflict.status_code == 409 and conflict.json()["code"] == "SCHEDULE_VERSION_CONFLICT"
    assert (await client.post(path + "/preview", headers=TOKEN)).status_code == 200
    async with factory() as session:
        assert (
            await count(session, AlertScheduleRun) == await count(session, NotificationOutbox) == 0
        )
    assert (await client.delete(path + "?version=1", headers=TOKEN)).status_code == 409
    assert (await client.delete(path + "?version=2", headers=TOKEN)).status_code == 204
    assert (await client.get(path, headers=TOKEN)).status_code == 404
    assert (await client.get(PREFIX + "/schedules", headers=TOKEN)).json()["items"] == []
    async with factory() as session:
        assert (await session.get(AlertSchedule, row["id"])).is_deleted


async def test_api_auth_validation_capacity(client, factory):
    assert (await client.get(PREFIX + "/schedules")).status_code == 401
    for path in ("/schedule-runs?page=0", "/schedule-runs?page_size=101"):
        assert (await client.get(PREFIX + path, headers=TOKEN)).status_code == 422
    for _ in range(50):
        await add(factory, enabled=False)
    response = await client.post(PREFIX + "/schedules", json=BODY, headers=TOKEN)
    assert response.status_code == 409 and response.json()["code"] == "SCHEDULE_CAPACITY_EXCEEDED"
    assert (
        await client.get(PREFIX + "/schedules/" + str(uuid4()), headers=TOKEN)
    ).status_code == 404
    client.test_app.state.settings.api_token = SecretStr("")
    assert (await client.get(PREFIX + "/schedules", headers=TOKEN)).status_code == 503


def test_domain_rejects_naive_and_clips_close():
    cal = Calendar(
        date(2026, 11, 23),
        True,
        "REGULAR_SESSION",
        "KNOWN",
        date(2026, 1, 1),
        date(2026, 12, 31),
        NOW - timedelta(hours=5),
        NOW + timedelta(seconds=60),
    )
    result = decide_slot(
        now=NOW,
        scheduled_at=NOW,
        active_since=NOW - timedelta(hours=1),
        grace_seconds=600,
        calendar=cal,
        enabled=True,
    )
    assert result.expires_at == NOW + timedelta(seconds=60)
    with pytest.raises(ValueError):
        decide_slot(
            now=NOW.replace(tzinfo=None),
            scheduled_at=NOW,
            active_since=NOW,
            grace_seconds=120,
            calendar=cal,
            enabled=True,
        )
    unknown = replace(cal, state="UNKNOWN")
    assert (
        decide_slot(
            now=NOW + timedelta(seconds=999),
            scheduled_at=NOW,
            active_since=NOW,
            grace_seconds=120,
            calendar=unknown,
            enabled=True,
        ).status
        == "SKIPPED"
    )
