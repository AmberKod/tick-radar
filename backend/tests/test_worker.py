import asyncio
import json

from cross_market.apps.worker.runtime import RELEASE, RENEW, WorkerRuntime
from cross_market.apps.worker.task_registry import TASKS_ENABLED, registered_tasks
from cross_market.shared.config import Settings


class MemoryRedis:
    def __init__(self):
        self.data = {}
        self.calls = []
        self.after_renew = None

    async def set(self, key, value, *, nx=False, ex=None):
        self.calls.append(("set", key, nx, ex))
        if nx and key in self.data:
            return False
        self.data[key] = value
        return True

    async def eval(self, script, numkeys, lock, heartbeat, owner, *args):
        self.calls.append((script, owner))
        assert numkeys == 2
        if self.data.get(lock) != owner:
            return 0
        if script == RENEW:
            self.data[heartbeat] = args[1]
            if self.after_renew:
                self.after_renew()
        elif script == RELEASE:
            self.data[heartbeat] = args[0]
            del self.data[lock]
        else:
            raise AssertionError("未预期脚本")
        return 1


async def test_contender_never_touches_owner_heartbeat():
    redis = MemoryRedis()
    settings = Settings()
    redis.data = {settings.worker_lock_key: "other", settings.worker_heartbeat_key: "original"}
    worker = WorkerRuntime(redis, settings)
    assert await worker.run() == 1
    assert redis.data[settings.worker_heartbeat_key] == "original"
    assert len(redis.calls) == 1
    assert redis.calls[0][2:] == (True, 30)


async def test_shutdown_releases_owned_lock_and_marks_stopping():
    redis = MemoryRedis()
    settings = Settings()
    worker = WorkerRuntime(redis, settings)
    redis.after_renew = worker.stop_event.set
    assert await worker.run() == 0
    assert settings.worker_lock_key not in redis.data
    heartbeat = json.loads(redis.data[settings.worker_heartbeat_key])
    assert heartbeat["status"] == "stopping"
    assert heartbeat["instance_id"] == worker.owner
    assert registered_tasks() == () and TASKS_ENABLED is False


async def test_lock_loss_stops_and_preserves_new_owner():
    redis = MemoryRedis()
    settings = Settings(worker_heartbeat_interval_seconds=0.001)
    worker = WorkerRuntime(redis, settings)

    def replace_owner():
        redis.data[settings.worker_lock_key] = "replacement"
        redis.data[settings.worker_heartbeat_key] = "replacement-heartbeat"

    redis.after_renew = replace_owner
    assert await asyncio.wait_for(worker.run(), 1) == 1
    assert redis.data[settings.worker_lock_key] == "replacement"
    assert redis.data[settings.worker_heartbeat_key] == "replacement-heartbeat"


async def test_cancellation_releases_lease():
    redis = MemoryRedis()
    worker = WorkerRuntime(redis, Settings())
    entered = asyncio.Event()
    redis.after_renew = entered.set
    task = asyncio.create_task(worker.run())
    await entered.wait()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert worker.settings.worker_lock_key not in redis.data
