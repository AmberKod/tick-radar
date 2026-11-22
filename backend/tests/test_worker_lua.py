import json

from fakeredis.aioredis import FakeRedis

from cross_market.apps.worker.runtime import WorkerRuntime
from cross_market.shared.config import Settings


async def test_lua_lease_ttl_ownership_and_heartbeat():
    redis = FakeRedis(decode_responses=True)
    settings = Settings()
    first = WorkerRuntime(redis, settings)
    second = WorkerRuntime(redis, settings)
    try:
        assert first.owner != second.owner
        assert await redis.set(settings.worker_lock_key, first.owner, nx=True, ex=30)
        assert await first.renew()
        assert 0 < await redis.ttl(settings.worker_lock_key) <= 30
        assert 0 < await redis.ttl(settings.worker_heartbeat_key) <= 30
        original = await redis.get(settings.worker_heartbeat_key)
        assert json.loads(original)["status"] == "running"
        assert not await second.renew()
        await second.release()
        assert await redis.get(settings.worker_lock_key) == first.owner
        assert await redis.get(settings.worker_heartbeat_key) == original
        await first.release()
        assert await redis.get(settings.worker_lock_key) is None
        assert json.loads(await redis.get(settings.worker_heartbeat_key))["status"] == "stopping"
        assert await redis.set(settings.worker_lock_key, second.owner, nx=True, ex=30)
        assert not await first.renew()
        assert await second.renew()
    finally:
        await redis.aclose()
