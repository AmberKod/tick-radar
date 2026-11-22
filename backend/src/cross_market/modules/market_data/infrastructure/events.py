import asyncio

import anyio

from cross_market.modules.market_data.infrastructure.cache import QUOTE_CHANNEL


async def close_subscription(subscription):
    # 客户端断开会取消整个响应作用域，清理必须短暂屏蔽该取消。
    with anyio.CancelScope(shield=True):
        try:
            with anyio.move_on_after(2):
                await subscription.unsubscribe(QUOTE_CHANNEL)
                while True:
                    message = await subscription.get_message(timeout=0.1)
                    if message is None or message["type"] == "unsubscribe":
                        break
        except Exception:
            pass
        finally:
            with anyio.move_on_after(2):
                try:
                    await subscription.aclose()
                except Exception:
                    pass


class RedisQuoteEvents:
    """订阅只传失效通知；重新读取共享快照，避免积压旧报价。"""

    def __init__(self, redis):
        self.redis = redis

    async def subscribe(self):
        subscription = self.redis.pubsub()
        try:
            async with asyncio.timeout(3):
                await subscription.subscribe(QUOTE_CHANNEL)
                # 确认订阅已生效后才能读初始快照，关闭快照与增量之间的空窗。
                while True:
                    message = await subscription.get_message(timeout=0.5)
                    if message and message["type"] == "subscribe":
                        break
            return subscription
        except BaseException:
            await close_subscription(subscription)
            raise
