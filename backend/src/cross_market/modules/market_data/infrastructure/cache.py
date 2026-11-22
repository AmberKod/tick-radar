from uuid import uuid4

LEASE_SECONDS = 15
QUOTE_CHANNEL = "market:quote.updated"

PUBLISH = """
if redis.call('get', KEYS[1]) ~= ARGV[1] then return 0 end
if #KEYS == 3 and redis.call('get', KEYS[3]) ~= ARGV[4] then return 0 end
redis.call('set', KEYS[2], ARGV[2], 'EX', ARGV[3])
redis.call('publish', 'market:quote.updated', KEYS[2])
return 1
"""

BUDGET = """
local window = math.floor(tonumber(redis.call('TIME')[1]) / 60)
local key = KEYS[1] .. ':' .. window
local count = tonumber(redis.call('get', key) or '0')
if count >= 30 then return 0 end
redis.call('incr', key)
redis.call('expire', key, 120)
return 1
"""


class RedisQuoteCache:
    def __init__(self, redis):
        self.redis = redis

    async def read(self, symbol: str) -> str | None:
        return await self.redis.get(f"market:quote:{symbol}")

    async def read_many(self, symbols: list[str]) -> list[str | None]:
        return await self.redis.mget([f"market:quote:{symbol}" for symbol in symbols])

    async def write(
        self,
        symbol: str,
        payload: str,
        owner: str | None = None,
        ttl: int = 3600,
        publication_guard: tuple[str, str] | None = None,
    ) -> bool:
        if owner is None:
            # 无owner入口仅用于测试预加载；生产刷新始终传入租约owner。
            if publication_guard is not None:
                return False
            await self.redis.set(f"market:quote:{symbol}", payload, ex=ttl)
            return True
        keys = [f"market:refresh:{symbol}", f"market:quote:{symbol}"]
        arguments = [owner, payload, ttl]
        if publication_guard is not None:
            keys.append(publication_guard[0])
            arguments.append(publication_guard[1])
        return bool(await self.redis.eval(PUBLISH, len(keys), *keys, *arguments))

    async def acquire(self, symbol: str) -> str | None:
        owner = uuid4().hex
        acquired = await self.redis.set(
            f"market:refresh:{symbol}", owner, nx=True, ex=LEASE_SECONDS
        )
        return owner if acquired else None

    async def take_budget(self) -> bool:
        return bool(await self.redis.eval(BUDGET, 1, "market:upstream:budget"))
