"""后台任务诊断与进程心跳分开，失败不能被解释为行情采集正常。"""

import asyncio
import json
from datetime import UTC, datetime

from cross_market.modules.system.application.schemas import TaskStatus

KEY = "health:worker:task:quote_collector"
DETAILS = {
    "success": "观察报价已更新，开市时效尚未验收",
    "partial": "部分自选报价更新失败，已保留错误标记",
    "error": "采集失败，请检查网络或数据服务",
    "idle": "暂无自选证券，添加后自动采集",
}


def parse_status(raw: str | None, interval: int) -> TaskStatus:
    if not raw:
        return TaskStatus(name="quote_collector", status="waiting", detail="等待后台采集任务")
    try:
        payload = json.loads(raw)
        checked = datetime.fromisoformat(payload["checked_at"])
        age = (datetime.now(UTC) - checked).total_seconds()
        state = payload["state"]
        if state not in DETAILS or not 0 <= age <= max(120, interval * 4):
            return TaskStatus(
                name="quote_collector", status="stale", detail="采集诊断已过期或时间异常"
            )
        return TaskStatus(
            name="quote_collector",
            status=state,
            detail=DETAILS[state],
            checked_at=checked,
            last_success_at=payload.get("last_success_at"),
            symbol_count=payload.get("symbol_count"),
        )
    except (ValueError, TypeError, KeyError, OverflowError):
        return TaskStatus(name="quote_collector", status="unknown", detail="采集诊断不可解析")


async def task_statuses(redis, settings) -> list[TaskStatus]:
    alert = TaskStatus(name="alert_engine", status="disabled", detail="实时预警未启用")
    if not settings.market_observation_enabled:
        return [
            TaskStatus(name="quote_collector", status="disabled", detail="观察报价已关闭"),
            alert,
        ]
    try:
        async with asyncio.timeout(settings.probe_timeout_seconds):
            raw = await redis.get(KEY)
        quote = parse_status(raw, settings.quote_refresh_interval_seconds)
    except Exception:
        quote = TaskStatus(
            name="quote_collector", status="unknown", detail="缓存不可读，无法判断采集任务"
        )
    return [quote, alert]
