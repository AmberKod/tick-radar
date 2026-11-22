import asyncio
from datetime import UTC, datetime
from time import monotonic
from uuid import uuid4

from cross_market.modules.market_data.application.schemas import QuoteError, QuoteStreamEvent
from cross_market.modules.market_data.infrastructure.events import close_subscription
from cross_market.shared.exceptions import AppError


class QuoteStreamSession:
    def __init__(self, service, symbols, subscription, initial):
        self.service = service
        self.symbols = symbols
        self.subscription = subscription
        self.initial = initial
        self.closed = False

    async def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            await close_subscription(self.subscription)
        finally:
            self.service.active.discard(self)

    def event(self, kind, *, snapshot=None, error=None):
        return QuoteStreamEvent(
            id=uuid4().hex,
            event=kind,
            symbols=self.symbols,
            quotes=snapshot.quotes if snapshot else [],
            checked_at=snapshot.checked_at if snapshot else datetime.now(UTC),
            error=error,
        )

    @staticmethod
    def fingerprint(snapshot):
        # 缓存年龄随时间变化；只在报价、错误或质量发生变化时重发全量。
        return tuple(
            quote.model_dump_json(exclude={"cache_age_seconds"}) for quote in snapshot.quotes
        )

    async def events(self, disconnected):
        current = self.initial
        last_signature = self.fingerprint(current)
        last_sent = monotonic()
        started = last_sent
        try:
            yield self.event("snapshot", snapshot=current)
            while not self.closed:
                if await disconnected():
                    return
                if monotonic() - started >= self.service.max_lifetime:
                    yield self.event(
                        "error",
                        error=QuoteError(
                            code="STREAM_RECONNECT", message="连接轮换，正在重新同步报价"
                        ),
                    )
                    return
                message = await self.subscription.get_message(
                    ignore_subscribe_messages=True, timeout=self.service.read_interval
                )
                changed = bool(
                    message
                    and message.get("type") == "message"
                    and message.get("data") in self.service.keys(self.symbols)
                )
                if changed:
                    # 合并同一批证券更新的通知；有界读取防止慢客户端积压。
                    for _ in range(100):
                        extra = await self.subscription.get_message(
                            ignore_subscribe_messages=True, timeout=0
                        )
                        if extra is None:
                            break
                now = monotonic()
                if changed or now - last_sent >= self.service.heartbeat_interval:
                    current = await self.service.quotes.snapshot(self.symbols)
                    signature = self.fingerprint(current)
                    if signature != last_signature:
                        yield self.event("quote.updated", snapshot=current)
                        last_signature = signature
                    else:
                        yield self.event("heartbeat")
                    last_sent = monotonic()
        except asyncio.CancelledError:
            raise
        except Exception:
            # 流已发送响应头，错误通过稳定事件通知；绝不透传Redis连接信息。
            yield self.event(
                "error",
                error=QuoteError(
                    code="STREAM_UNAVAILABLE", message="报价推送暂不可用，正在重新连接"
                ),
            )
        finally:
            await self.close()


class QuoteStreamService:
    def __init__(
        self,
        quotes,
        events,
        *,
        max_connections=8,
        heartbeat_interval=10,
        read_interval=0.5,
        max_lifetime=300,
    ):
        self.quotes = quotes
        self.events = events
        self.max_connections = max_connections
        self.heartbeat_interval = heartbeat_interval
        self.read_interval = read_interval
        self.max_lifetime = max_lifetime
        self.active = set()
        self._opening = 0

    @staticmethod
    def keys(symbols):
        return {f"market:quote:{symbol}" for symbol in symbols}

    async def open(self, symbols):
        # 单个API进程内不跨await检查/占位，限制已建立和建立中的连接总量。
        if len(self.active) + self._opening >= self.max_connections:
            raise AppError(429, "STREAM_LIMIT", "报价推送连接过多，请关闭多余页面")
        self._opening += 1
        subscription = None
        try:
            subscription = await self.events.subscribe()
            initial = await self.quotes.snapshot(symbols)
            session = QuoteStreamSession(self, symbols, subscription, initial)
            self.active.add(session)
            return session
        except asyncio.CancelledError:
            if subscription:
                await close_subscription(subscription)
            raise
        except Exception as exc:
            if subscription:
                await close_subscription(subscription)
            raise AppError(503, "STREAM_UNAVAILABLE", "共享报价推送暂不可用") from exc
        finally:
            self._opening -= 1

    async def close(self):
        await asyncio.gather(*(session.close() for session in tuple(self.active)))
