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
ALERT_DETAILS = {
    "success": "观察规则已评估；实时风控尚未验收",
    "partial": "部分规则跳过，报价覆盖或质量不足",
    "error": "观察规则评估失败",
    "idle": "暂无启用的观察规则",
}
NOTIFICATION_DETAILS = {
    "success": "站内通知已投递",
    "partial": "部分站内通知未完成投递",
    "error": "站内通知投递失败",
    "idle": "暂无待投递的站内通知",
}


def parse_status(raw, interval: int, name="quote_collector", details=None) -> TaskStatus:
    details = DETAILS if details is None else details
    if raw is None or raw == "":
        return TaskStatus(name=name, status="waiting", detail="等待后台任务")
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("诊断结构无效")
        checked = datetime.fromisoformat(payload["checked_at"])
        age = (datetime.now(UTC) - checked).total_seconds()
        state = payload["state"]
        if state not in details or not 0 <= age <= max(120, interval * 4):
            return TaskStatus(name=name, status="stale", detail="任务诊断已过期或时间异常")
        return TaskStatus(
            name=name,
            status=state,
            detail=details[state],
            checked_at=checked,
            last_success_at=payload.get("last_success_at"),
            symbol_count=payload.get("symbol_count"),
        )
    except (ValueError, TypeError, KeyError, OverflowError):
        return TaskStatus(name=name, status="unknown", detail="任务诊断不可解析")


async def task_statuses(redis, settings) -> list[TaskStatus]:
    market = getattr(settings, "market_observation_enabled", True)
    specs = (
        (
            "quote_collector",
            market,
            getattr(settings, "quote_refresh_interval_seconds", 30),
            DETAILS,
        ),
        (
            "alert_engine",
            market and getattr(settings, "alert_observation_enabled", True),
            getattr(settings, "alert_scan_interval_seconds", 5),
            ALERT_DETAILS,
        ),
        (
            "notification_dispatcher",
            True,
            getattr(settings, "notification_dispatch_interval_seconds", 2),
            NOTIFICATION_DETAILS,
        ),
    )
    tasks = []
    for name, enabled, interval, details in specs:
        if not enabled:
            tasks.append(TaskStatus(name=name, status="disabled", detail="观察任务已关闭"))
            continue
        try:
            async with asyncio.timeout(settings.probe_timeout_seconds):
                raw = await redis.get(f"health:worker:task:{name}")
            tasks.append(parse_status(raw, interval, name, details))
        except Exception:
            tasks.append(TaskStatus(name=name, status="unknown", detail="缓存不可读，无法判断任务"))
    return tasks
