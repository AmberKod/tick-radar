import asyncio
import json
from datetime import UTC, datetime

from sqlalchemy import text

from cross_market.modules.system.application.schemas import ComponentStatus


class InfrastructureProbes:
    def __init__(self, engine, redis, settings):
        self.engine = engine
        self.redis = redis
        self.settings = settings

    async def mysql_status(self) -> ComponentStatus:
        try:
            async with asyncio.timeout(self.settings.probe_timeout_seconds):
                async with self.engine.connect() as connection:
                    await connection.execute(text("SELECT 1"))
            return ComponentStatus(status="healthy")
        except Exception:
            return ComponentStatus(status="unhealthy", detail="数据库探测失败")

    async def redis_and_worker_status(self) -> tuple[ComponentStatus, ComponentStatus]:
        try:
            async with asyncio.timeout(self.settings.probe_timeout_seconds):
                await self.redis.ping()
                raw = await self.redis.get(self.settings.worker_heartbeat_key)
        except Exception:
            return (
                ComponentStatus(status="unhealthy", detail="缓存探测失败"),
                ComponentStatus(status="unknown", detail="缓存不可读，无法判断 Worker"),
            )
        redis_status = ComponentStatus(status="healthy")
        if raw:
            try:
                payload = json.loads(raw)
                heartbeat = datetime.fromisoformat(payload["heartbeat_at"])
                age = (datetime.now(UTC) - heartbeat).total_seconds()
                if (
                    payload["status"] == "running"
                    and payload["worker_name"] == self.settings.worker_name
                    and 0 <= age < self.settings.worker_heartbeat_ttl_seconds
                ):
                    return redis_status, ComponentStatus(status="healthy")
            except (ValueError, TypeError, KeyError, OverflowError):
                pass
        return redis_status, ComponentStatus(status="stale", detail="Worker 心跳缺失或过期")
