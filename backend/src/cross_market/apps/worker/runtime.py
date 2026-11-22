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
    def __init__(self, redis, settings, tasks=None):
        self.redis = redis
        self.settings = settings
        self.owner = uuid4().hex
        self.started_at = datetime.now(UTC).isoformat()
        self.stop_event = asyncio.Event()
        self.tasks = registered_tasks() if tasks is None else tuple(tasks)

    def heartbeat(self, status: str) -> str:
        return json.dumps(
            {
                "worker_name": self.settings.worker_name,
                "status": status,
                "version": self.settings.version,
                "instance_id": self.owner,
                "started_at": self.started_at,
                "heartbeat_at": datetime.now(UTC).isoformat(),
                "tasks_enabled": bool(self.tasks),
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
        running = []
        try:
            if not await self.renew():
                return 1
            if not self.stop_event.is_set():
                running = [asyncio.create_task(callback(self)) for callback in self.tasks]
            while not self.stop_event.is_set():
                try:
                    await asyncio.wait_for(
                        self.stop_event.wait(), self.settings.worker_heartbeat_interval_seconds
                    )
                except TimeoutError:
                    pass
                if self.stop_event.is_set():
                    break
                if any(task.done() for task in running) or not await self.renew():
                    return 1
            return 0
        finally:
            for task in running:
                task.cancel()
            await asyncio.gather(*running, return_exceptions=True)
            # 先取消采集，再释放所有权；旧实例不能改写新实例状态。
            await self.release()
