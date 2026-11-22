import asyncio
from datetime import UTC, datetime

from cross_market.modules.system.application.registry import disabled_tasks
from cross_market.modules.system.application.schemas import (
    Components,
    ComponentStatus,
    SystemStatus,
)


class HealthService:
    def __init__(self, probes, version: str):
        self.probes = probes
        self.version = version

    async def status(self) -> SystemStatus:
        mysql, (redis, worker) = await asyncio.gather(
            self.probes.mysql_status(), self.probes.redis_and_worker_status()
        )
        status = "healthy"
        if mysql.status != "healthy":
            status = "unhealthy"
        elif redis.status != "healthy" or worker.status != "healthy":
            status = "degraded"
        return SystemStatus(
            status=status,
            checked_at=datetime.now(UTC),
            version=self.version,
            components=Components(
                api=ComponentStatus(status="healthy"), mysql=mysql, redis=redis, worker=worker
            ),
            tasks=(await self.probes.task_statuses())
            if hasattr(self.probes, "task_statuses")
            else disabled_tasks(),
            market_data_enabled=bool(
                getattr(getattr(self.probes, "settings", None), "market_observation_enabled", False)
            ),
        )
