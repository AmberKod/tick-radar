import logging
import re
import time
from uuid import uuid4

from fastapi import Request
from starlette.exceptions import HTTPException

from cross_market.shared.exceptions import error_response

REQUEST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")


def register_middleware(app):
    @app.middleware("http")
    async def request_id(request: Request, call_next):
        supplied = request.headers.get("X-Request-ID")
        request.state.trace_id = (
            supplied if supplied and REQUEST_ID.fullmatch(supplied) else uuid4().hex
        )
        if supplied is not None and not REQUEST_ID.fullmatch(supplied):
            return error_response(request, 400, "INVALID_REQUEST_ID", "请求 ID 格式无效")
        started = time.perf_counter()
        logger = logging.getLogger(__name__)
        try:
            response = await call_next(request)
        except Exception as exc:
            # 保留错误类型和关联 ID，避免堆栈或输入值泄露凭证。
            logger.error(
                "",
                extra={
                    "event": "request_failed",
                    "trace_id": request.state.trace_id,
                    "exception_type": type(exc).__name__,
                },
            )
            response = error_response(request, 500, "INTERNAL_ERROR", "服务器内部错误")
        response.headers["X-Request-ID"] = request.state.trace_id
        logger.info(
            "",
            extra={
                "event": "request_completed",
                "trace_id": request.state.trace_id,
                "method": request.method,
                "status_code": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return error_response(request, exc.status_code, f"HTTP_{exc.status_code}", "请求无法处理")
