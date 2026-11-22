import hashlib
import json
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext

from cross_market.modules.alerts.domain.engine import Rule, Sample, evaluate
from cross_market.modules.alerts.infrastructure import repository as repo
from cross_market.modules.alerts.infrastructure.models import AlertEvent
from cross_market.modules.market_data.application.schemas import QuoteDTO
from cross_market.modules.securities.application.service import get_security
from cross_market.shared.exceptions import AppError


def domain_rule(row):
    return Rule(
        row.rule_type,
        Decimal(row.threshold),
        Decimal(row.reset_threshold),
        row.cooldown_seconds,
        row.enabled,
        row.mode,
    )


def sample_for(quote, security, rule_type, now):
    if getattr(security, "status", "ACTIVE") != "ACTIVE":
        return None, "证券已停用"
    if quote is None:
        return None, "缓存快照缺少报价"
    if (
        quote.symbol != security.symbol
        or quote.currency != security.currency
        or quote.market != security.market
        or (quote.provider_exchange and quote.provider_exchange != security.exchange)
    ):
        return None, "报价证券身份或币种不匹配"
    if quote.error or quote.quality_status not in {"UNKNOWN", "MARKET_CLOSED"}:
        return None, "报价错误、过期或不可用"
    received = quote.received_at
    if received is None or received.tzinfo is None or received.utcoffset() is None:
        return None, "报价缺少有效接收时间"
    received = received.astimezone(UTC)
    age = (now - received).total_seconds()
    if not 0 <= age <= 180:
        return None, "报价接收时间在未来或超过180秒"
    try:
        price = Decimal(quote.price or "NaN")
        if not price.is_finite() or price <= 0:
            return None, "价格必须有限且大于零"
        value = price
        if rule_type.startswith("DAY_CHANGE"):
            previous = Decimal(quote.prev_close or "NaN")
            if not previous.is_finite() or previous <= 0:
                return None, "昨收必须有限且大于零"
            with localcontext() as context:
                context.prec = 80
                value = ((price - previous) / previous * 100).quantize(
                    Decimal("0.00000001"), rounding=ROUND_HALF_EVEN
                )
    except (InvalidOperation, ValueError, OverflowError):
        return None, "报价数值无效"
    canonical = json.dumps(
        [quote.symbol, quote.source, quote.source_time_raw, quote.price, quote.prev_close],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return Sample(value, hashlib.sha256(canonical.encode()).hexdigest(), received), ""


def evaluate_quote(row, state, quote, security, now):
    sample, reason = sample_for(quote, security, row.rule_type, now)
    return evaluate(domain_rule(row), state, sample, now, reason)


async def evaluate_rules(session, quotes: list[QuoteDTO], now: datetime) -> dict:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now 必须带时区")
    now = now.astimezone(UTC)
    await repo.lock_writes(session)
    targets = await repo.rules(session, active=True, limit=200)
    # 同一标的只接受最新接收样本，避免输入次序决定业务结果。
    by_symbol = {}
    for quote in quotes:
        prior = by_symbol.get(quote.symbol)
        if prior is None or (repo.utc(quote.received_at) or datetime.min.replace(tzinfo=UTC)) > (
            repo.utc(prior.received_at) or datetime.min.replace(tzinfo=UTC)
        ):
            by_symbol[quote.symbol] = quote
    counts = {"evaluated": 0, "triggered": 0, "skipped": 0}
    for target in targets:
        try:
            row = await repo.rule(session, target.id, lock=True)
        except AppError as error:
            # MySQL 候选读取后可能被另一事务归档，锁定重读以最新规则为准。
            if error.code != "ALERT_NOT_FOUND":
                raise
            counts["skipped"] += 1
            continue
        if not row.enabled or row.mode != "OBSERVATION":
            counts["skipped"] += 1
            continue
        stored = await repo.state(session, row.id, lock=True)
        before = repo.state_value(stored)
        security = await get_security(session, row.security_id)
        quote = by_symbol.get(security.symbol)
        result = evaluate_quote(row, before, quote, security, now)
        counts["evaluated"] += 1
        if not result.eligible:
            counts["skipped"] += 1
        if result.triggered and not await repo.event_exists(
            session, row.id, result.state.trigger_count
        ):
            from cross_market.modules.alerts.application.service import serialize_rule
            from cross_market.modules.notifications.application.service import enqueue

            snapshot = await serialize_rule(session, row, security=security)
            event = AlertEvent(
                rule_id=row.id,
                rule_version=row.version,
                trigger_number=result.state.trigger_count,
                rule_name=row.name,
                security_id=row.security_id,
                symbol=security.symbol,
                rule_type=row.rule_type,
                mode=row.mode,
                value=result.value,
                threshold=row.threshold,
                reason=result.state.evaluation_reason,
                sample_key=result.state.last_sample_key,
                rule_snapshot=snapshot.model_dump(mode="json"),
                quote=quote.model_dump(mode="json"),
                created_at=now,
            )
            session.add(event)
            await session.flush()
            event.outbox_id = await enqueue(
                session,
                event.id,
                f"观察提醒：{row.name}",
                event.reason,
                {
                    "event_id": event.id,
                    "rule_id": row.id,
                    "symbol": security.symbol,
                    "value": result.value,
                    "observation_only": True,
                },
            )
            counts["triggered"] += 1
        repo.save_state(stored, result.state)
        await session.flush()
    return counts
