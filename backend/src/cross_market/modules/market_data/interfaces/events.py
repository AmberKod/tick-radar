import anyio
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from cross_market.modules.market_data.application.schemas import QuoteStreamEvent, RefreshRequest
from cross_market.shared.exceptions import BUSINESS_ERROR_RESPONSES, AppError
from cross_market.shared.security import require_token

router = APIRouter(prefix="/api/v1/events", tags=["market-events"])


class QuoteStreamingResponse(StreamingResponse):
    def __init__(self, content, *, session, **kwargs):
        super().__init__(content, **kwargs)
        self.session = session

    async def __call__(self, scope, receive, send):
        async def bounded_send(message):
            # 慢客户端不能长期占用连接；最新状态由重连快照恢复。
            with anyio.fail_after(15):
                await send(message)

        try:
            await super().__call__(scope, receive, bounded_send)
        finally:
            # 首帧前断开或发送异常时，生成器可能尚未进入finally。
            await self.body_iterator.aclose()
            await self.session.close()


@router.get(
    "/stream",
    dependencies=[Depends(require_token)],
    response_model=QuoteStreamEvent,
    response_class=StreamingResponse,
    responses={
        **BUSINESS_ERROR_RESPONSES,
        200: {
            "content": {
                "text/event-stream": {"schema": {"$ref": "#/components/schemas/QuoteStreamEvent"}}
            },
            "description": "SSE帧data遵循QuoteStreamEvent，每次连接先发送全量快照",
        },
        429: {"description": "当前API进程已有8条推送连接"},
    },
)
async def quote_stream(request: Request, symbols: str = Query(max_length=2049)):
    try:
        parsed = RefreshRequest(symbols=symbols.split(",")).symbols
        selected = list(dict.fromkeys(parsed))
        if len(selected) > request.app.state.settings.quote_max_symbols:
            raise ValueError("证券数量超限")
    except ValueError as exc:
        raise AppError(422, "INVALID_SYMBOLS", "证券代码或数量无效") from exc
    session = await request.app.state.quote_stream.open(selected)

    async def frames():
        try:
            async for event in session.events(request.is_disconnected):
                yield f"id: {event.id}\nevent: {event.event}\ndata: {event.model_dump_json()}\n\n"
        finally:
            await session.close()

    return QuoteStreamingResponse(
        frames(),
        session=session,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )
