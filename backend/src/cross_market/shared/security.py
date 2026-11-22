import secrets
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from cross_market.shared.exceptions import AppError

bearer = HTTPBearer(auto_error=False)


async def require_token(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
):
    expected = request.app.state.settings.api_token.get_secret_value()
    if not expected:
        raise AppError(503, "AUTH_NOT_CONFIGURED", "尚未配置 API 令牌")
    if credentials is None or not secrets.compare_digest(
        credentials.credentials.encode(), expected.encode()
    ):
        raise AppError(401, "UNAUTHORIZED", "需要有效的 API 令牌")
