from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker

from cross_market.apps.api.bootstrap import register_modules
from cross_market.apps.api.middleware import register_middleware
from cross_market.modules.market_calendar.application.service import CalendarService
from cross_market.modules.market_data.application.service import QuoteService
from cross_market.modules.market_data.application.stream import QuoteStreamService
from cross_market.modules.market_data.infrastructure.events import RedisQuoteEvents
from cross_market.modules.system.application.health import HealthService
from cross_market.modules.system.infrastructure.probes import InfrastructureProbes
from cross_market.shared.config import Settings
from cross_market.shared.database import create_engine
from cross_market.shared.exceptions import register_exception_handlers
from cross_market.shared.logging import configure_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    calendar = CalendarService(settings.calendar_closed_dates)

    @asynccontextmanager
    async def lifespan(app):
        configure_logging(settings.log_level)
        await calendar.warmup()
        engine = create_engine(settings)
        app.state.engine = engine
        app.state.session_factory = async_sessionmaker(engine, expire_on_commit=False)
        redis = Redis.from_url(
            settings.redis_url.get_secret_value(),
            decode_responses=True,
            socket_connect_timeout=settings.probe_timeout_seconds,
            socket_timeout=settings.probe_timeout_seconds,
        )
        app.state.health_service = HealthService(
            InfrastructureProbes(engine, redis, settings), settings.version
        )
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(6, connect=2)) as client:
                app.state.quote_service = QuoteService(client, redis, settings, calendar=calendar)
                app.state.quote_stream = QuoteStreamService(
                    app.state.quote_service, RedisQuoteEvents(redis)
                )
                try:
                    yield
                finally:
                    await app.state.quote_stream.close()
        finally:
            try:
                await redis.aclose()
            finally:
                await engine.dispose()

    app = FastAPI(title="TickRadar API", version=settings.version, lifespan=lifespan)
    app.state.settings = settings
    app.state.market_calendar = calendar
    register_exception_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["X-Request-ID", "Authorization", "Content-Type"],
        expose_headers=["X-Request-ID"],
    )
    register_middleware(app)
    register_modules(app)
    return app


app = create_app()
