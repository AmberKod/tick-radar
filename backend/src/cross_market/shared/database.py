from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncAttrs, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from cross_market.shared.config import Settings


async def get_session(request: Request):
    """请求事务统一提交，任何异常均回滚。"""
    async with request.app.state.engine.connect() as connection:
        async with request.app.state.session_factory(bind=connection) as session:
            try:
                yield session
                await session.commit()
            except BaseException:
                # 取消请求同样先结束业务事务，清理回调不得提交未完成的写入。
                try:
                    await session.rollback()
                except BaseException:
                    await connection.invalidate()
                    session.info.pop("connection_finalizers", None)
                    raise
                raise
            finally:
                try:
                    for finalize in session.info.pop("connection_finalizers", []):
                        await finalize(connection)
                except BaseException:
                    await connection.invalidate()
                    raise


class Base(AsyncAttrs, DeclarativeBase):
    pass


def create_engine(settings: Settings):
    # 连接按需建立，数据库不可用时仍可提供诊断接口。
    return create_async_engine(settings.database_url, pool_pre_ping=True)
