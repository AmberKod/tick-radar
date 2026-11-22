import asyncio
import json
from datetime import UTC, datetime
from uuid import uuid4

from cross_market.apps.worker.task_registry import registered_tasks

# 同一 Lua 内校验所有权、续租和写心跳，阻止旧进程覆盖新实例。
RENEW = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
redis.call('EXPIRE', KEYS[1], ARGV[2])
redis.call('SET', KEYS[2], ARGV[3], 'EX', ARGV[4])
return 1
"""
RELEASE = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
redis.call('SET', KEYS[2], ARGV[2], 'EX', ARGV[3])
redis.call('DEL', KEYS[1])
return 1
"""


class WorkerRuntime:
    def __init__(self, redis, settings):
        self.redis = redis
        self.settings = settings
        self.owner = uuid4().hex
        self.started_at = datetime.now(UTC).isoformat()
        self.stop_event = asyncio.Event()
        self.tasks = registered_tasks()

    def heartbeat(self, status: str) -> str:
        return json.dumps(
            {
                "worker_name": self.settings.worker_name,
                "status": status,
                "version": self.settings.version,
                "instance_id": self.owner,
                "started_at": self.started_at,
                "heartbeat_at": datetime.now(UTC).isoformat(),
                "tasks_enabled": False,
            }
        )

    async def renew(self) -> bool:
        return bool(
            await self.redis.eval(
                RENEW,
                2,
                self.settings.worker_lock_key,
                self.settings.worker_heartbeat_key,
                self.owner,
                self.settings.worker_lock_ttl_seconds,
                self.heartbeat("running"),
                self.settings.worker_heartbeat_ttl_seconds,
            )
        )

    async def release(self) -> None:
        await self.redis.eval(
            RELEASE,
            2,
            self.settings.worker_lock_key,
            self.settings.worker_heartbeat_key,
            self.owner,
            self.heartbeat("stopping"),
            self.settings.worker_heartbeat_ttl_seconds,
        )

    async def run(self) -> int:
        acquired = await self.redis.set(
            self.settings.worker_lock_key,
            self.owner,
            nx=True,
            ex=self.settings.worker_lock_ttl_seconds,
        )
        if not acquired:
            return 1
        try:
            while not self.stop_event.is_set():
                if not await self.renew():
                    return 1
                try:
                    await asyncio.wait_for(
                        self.stop_event.wait(), self.settings.worker_heartbeat_interval_seconds
                    )
                except TimeoutError:
                    pass
            return 0
        finally:
            # 未持有锁时 Lua 为无操作，不影响其他进程的心跳和锁。
            await self.release()
