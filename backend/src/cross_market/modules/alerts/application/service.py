from dataclasses import asdict, replace
from datetime import UTC, datetime

from cross_market.modules.alerts.application.evaluation import evaluate_quote
from cross_market.modules.alerts.application.schemas import (
    AlertEventPage,
    AlertEventResponse,
    AlertPreviewResponse,
    AlertRuleResponse,
    AlertStateResponse,
)
from cross_market.modules.alerts.domain.engine import State, clear_baseline
from cross_market.modules.alerts.infrastructure import repository as repo
from cross_market.modules.alerts.infrastructure.models import AlertRule, AlertRuleState
from cross_market.modules.securities.application.service import get_securities, get_security
from cross_market.shared.exceptions import AppError


def verify_mode(body):
    if body.mode == "REALTIME" and body.enabled:
        raise AppError(422, "REALTIME_NOT_VERIFIED", "来源时效未经验证，不能启用实时提醒")


async def serialize_rule(session, row, *, security=None):
    security = security or await get_security(session, row.security_id)
    stored = await repo.state(session, row.id)
    values = {column.name: getattr(row, column.name) for column in AlertRule.__table__.columns}
    return AlertRuleResponse(
        **values,
        symbol=security.symbol,
        security_name=security.name,
        state=AlertStateResponse.model_validate(stored),
    )


async def list_quote_targets(session, limit=50):
    rows = await repo.rules(session, active=True, limit=200)
    securities = await get_securities(session, [row.security_id for row in rows])
    symbols = list(dict.fromkeys(securities[row.security_id].symbol for row in rows))
    return symbols[: max(0, min(limit, 200))]


async def get_rule(session, rule_id):
    return await serialize_rule(session, await repo.rule(session, rule_id))


async def list_rules(session):
    return {"items": [await serialize_rule(session, row) for row in await repo.rules(session)]}


async def create_rule(session, body):
    verify_mode(body)
    await repo.lock_writes(session)
    await repo.ensure_capacity(session)
    security = await get_security(session, body.security_id)
    if security.status != "ACTIVE":
        raise AppError(422, "SECURITY_INACTIVE", "证券已停用，不能创建观察规则")
    row = AlertRule(**body.model_dump())
    session.add(row)
    await session.flush()
    state = State(phase="ARMED" if row.enabled else "DISABLED")
    session.add(AlertRuleState(rule_id=row.id, **asdict(state)))
    await session.flush()
    return await serialize_rule(session, row)


async def locked_version(session, rule_id, version):
    await repo.lock_writes(session)
    row = await repo.rule(session, rule_id, lock=True)
    if row.version != version:
        raise AppError(409, "ALERT_VERSION_CONFLICT", "提醒规则已变更，请重新加载")
    stored = await repo.state(session, row.id, lock=True)
    return row, stored


async def update_rule(session, rule_id, body):
    verify_mode(body)
    row, stored = await locked_version(session, rule_id, body.version)
    security = await get_security(session, body.security_id)
    if body.enabled and security.status != "ACTIVE":
        raise AppError(422, "SECURITY_INACTIVE", "证券已停用，不能启用观察规则")
    now = datetime.now(UTC)
    await repo.versioned_change(
        session, row, body.version, {**body.model_dump(exclude={"version"}), "updated_at": now}
    )
    state = clear_baseline(repo.state_value(stored), phase="ARMED" if row.enabled else "DISABLED")
    repo.save_state(stored, replace(state, evaluation_status="PENDING", checked_at=None))
    await session.flush()
    return await serialize_rule(session, row)


async def delete_rule(session, rule_id, version):
    row, stored = await locked_version(session, rule_id, version)
    await repo.versioned_change(
        session,
        row,
        version,
        {"is_deleted": True, "enabled": False, "updated_at": datetime.now(UTC)},
    )
    repo.save_state(
        stored,
        replace(
            clear_baseline(repo.state_value(stored), phase="DISABLED"), evaluation_status="DISABLED"
        ),
    )
    await session.flush()


async def reset_rule(session, rule_id, version):
    row, stored = await locked_version(session, rule_id, version)
    now = datetime.now(UTC)
    await repo.versioned_change(session, row, version, {"updated_at": now})
    state = clear_baseline(repo.state_value(stored), phase="ARMED" if row.enabled else "DISABLED")
    repo.save_state(
        stored, replace(state, last_reset_at=now, evaluation_status="RESET", checked_at=None)
    )
    await session.flush()
    return await serialize_rule(session, row)


async def preview_rule(session, rule_id, quote_service):
    row = await repo.rule(session, rule_id)
    stored = await repo.state(session, rule_id)
    before = repo.state_value(stored)
    security = await get_security(session, row.security_id)
    now = datetime.now(UTC)
    quote = None
    try:
        snapshot = await quote_service.snapshot([security.symbol])
        quote = next((item for item in snapshot.quotes if item.symbol == security.symbol), None)
    except Exception:
        # 缓存故障只模拟中断基线，不写入状态，也不回退到网络取价。
        pass
    now = datetime.now(UTC)
    result = evaluate_quote(row, before, quote, security, now)
    return AlertPreviewResponse(
        rule_id=row.id,
        eligible=result.eligible,
        would_trigger=result.triggered,
        value=result.value,
        status=result.state.evaluation_status,
        reason=result.state.evaluation_reason,
        quote=quote,
        state_before=AlertStateResponse(**asdict(before)),
        state_after=AlertStateResponse(**asdict(result.state)),
    )


async def list_events(session, *, rule_id=None, page=1, page_size=20):
    rows, total = await repo.events(session, rule_id, page, page_size)
    return AlertEventPage(
        items=[AlertEventResponse.model_validate(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )
