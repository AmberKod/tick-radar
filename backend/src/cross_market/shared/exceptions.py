from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError, SQLAlchemyError


class ErrorResponse(BaseModel):
    code: str
    message: str
    trace_id: str
    details: dict | list | None = None


BUSINESS_ERROR_RESPONSES = {
    status: {"model": ErrorResponse} for status in (401, 404, 409, 422, 503)
}


class AppError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


def error_response(request: Request, status: int, code: str, message: str):
    trace_id = getattr(request.state, "trace_id", uuid4().hex)
    return JSONResponse(
        status_code=status,
        content=ErrorResponse(code=code, message=message, trace_id=trace_id).model_dump(),
        headers={"X-Request-ID": trace_id},
    )


def register_exception_handlers(app: FastAPI):
    @app.exception_handler(AppError)
    async def application_error(request: Request, exc: AppError):
        return error_response(request, exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return error_response(request, 422, "VALIDATION_ERROR", "请求参数无效")

    @app.exception_handler(IntegrityError)
    async def integrity_error(request: Request, exc: IntegrityError):
        return error_response(request, 409, "CONFLICT", "数据重复或引用冲突")

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, exc: SQLAlchemyError):
        return error_response(request, 503, "DATABASE_UNAVAILABLE", "数据库暂不可用")
