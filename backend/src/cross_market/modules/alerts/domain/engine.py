"""观察提醒纯状态机；不依赖数据库、报价 DTO 或交易日历。"""

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal

OBSERVATION = "观察提醒，非实时风控；日涨跌幅不会按交易日自动重置"


@dataclass(frozen=True)
class Rule:
    rule_type: str
    threshold: Decimal
    reset_threshold: Decimal
    cooldown_seconds: int = 300
    enabled: bool = True
    mode: str = "OBSERVATION"


@dataclass(frozen=True)
class State:
    phase: str = "ARMED"
    last_value: str | None = None
    last_sample_key: str | None = None
    last_received_at: datetime | None = None
    last_triggered_at: datetime | None = None
    last_reset_at: datetime | None = None
    evaluation_status: str = "PENDING"
    evaluation_reason: str = OBSERVATION
    checked_at: datetime | None = None
    trigger_count: int = 0


@dataclass(frozen=True)
class Sample:
    value: Decimal
    key: str
    received_at: datetime


@dataclass(frozen=True)
class Result:
    state: State
    triggered: bool = False
    eligible: bool = False
    value: str | None = None


def clear_baseline(state: State, *, phase=None) -> State:
    return replace(
        state,
        phase=phase or state.phase,
        last_value=None,
        last_sample_key=None,
        last_received_at=None,
    )


def evaluate(
    rule: Rule,
    state: State,
    sample: Sample | None,
    now: datetime,
    invalid_reason: str = "报价缺失或不可用",
) -> Result:
    def finish(current, status, reason, *, triggered=False, eligible=False, value=None):
        current = replace(
            current,
            checked_at=now,
            evaluation_status=status,
            evaluation_reason=f"{OBSERVATION}；{reason}",
        )
        return Result(current, triggered, eligible, value)

    if not rule.enabled:
        return finish(clear_baseline(state, phase="DISABLED"), "DISABLED", "规则已关闭")
    if rule.mode != "OBSERVATION":
        return finish(clear_baseline(state), "REALTIME_NOT_VERIFIED", "实时来源未经验证")
    if sample is None:
        return finish(clear_baseline(state), "SKIPPED", invalid_reason)
    value = str(sample.value)
    if state.last_received_at and sample.received_at <= state.last_received_at:
        return finish(state, "OLD_SAMPLE", "接收时间未前进", value=value)
    if sample.key == state.last_sample_key:
        return finish(state, "DUPLICATE", "源端内容相同", value=value)
    # 长时间中断后的第一笔仅作为新的穿越基线。
    if (
        state.last_received_at
        and (sample.received_at - state.last_received_at).total_seconds() > 180
    ):
        state = clear_baseline(state)
    previous = Decimal(state.last_value) if state.last_value is not None else None
    current = replace(
        state,
        phase="ARMED" if state.phase == "DISABLED" else state.phase,
        last_value=value,
        last_sample_key=sample.key,
        last_received_at=sample.received_at,
    )
    upward = rule.rule_type in {"PRICE_CROSS_UP", "DAY_CHANGE_ABOVE"}
    if current.phase == "TRIGGERED":
        reset = (
            sample.value <= rule.reset_threshold if upward else sample.value >= rule.reset_threshold
        )
        if reset:
            current = replace(current, phase="ARMED", last_reset_at=now)
            return finish(current, "RESET", "已进入复位区，本笔不触发", eligible=True, value=value)
        return finish(current, "TRIGGERED", "等待进入复位区", eligible=True, value=value)
    if rule.rule_type.startswith("PRICE_CROSS"):
        if previous is None:
            return finish(current, "BASELINE", "首笔建立穿越基线", eligible=True, value=value)
        hit = (
            previous < rule.threshold <= sample.value
            if upward
            else previous > rule.threshold >= sample.value
        )
    else:
        hit = sample.value >= rule.threshold if upward else sample.value <= rule.threshold
    if (
        hit
        and state.last_triggered_at
        and (now - state.last_triggered_at).total_seconds() < rule.cooldown_seconds
    ):
        return finish(current, "COOLDOWN", "冷却期间只更新基线", eligible=True, value=value)
    if hit:
        current = replace(
            current, phase="TRIGGERED", last_triggered_at=now, trigger_count=state.trigger_count + 1
        )
        return finish(
            current, "TRIGGERED", "观察条件满足", triggered=True, eligible=True, value=value
        )
    return finish(current, "ARMED", "观察条件未满足", eligible=True, value=value)
