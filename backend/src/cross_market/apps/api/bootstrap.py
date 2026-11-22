from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from cross_market.modules.market_data.interfaces.router import router as market_router
from cross_market.modules.securities.interfaces.router import router as securities_router
from cross_market.modules.system.interfaces.router import router
from cross_market.modules.watchlist.interfaces.router import router as watchlist_router
from cross_market.shared.security import require_token

auth_router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class SessionStatus(BaseModel):
    authenticated: Literal[True] = True


@auth_router.get("/session", response_model=SessionStatus, dependencies=[Depends(require_token)])
async def auth_session():
    return {"authenticated": True}


def register_modules(app):
    app.include_router(router)
    app.include_router(auth_router)
    app.include_router(securities_router)
    app.include_router(watchlist_router)
    app.include_router(market_router)
