from hashlib import sha256

from sqlalchemy import text

from cross_market.shared.exceptions import AppError


async def lock_watchlist(session):
    """空分组集合也串行化，连接锁在请求事务结束后释放。"""
    if session.info.get("watchlist_lock"):
        return
    connection = await session.connection()
    if connection.dialect.name == "mysql":
        database = await session.scalar(text("SELECT DATABASE()"))
        namespace = sha256(str(database).encode()).hexdigest()[:40]
        key = f"tickradar:{namespace}:watchlist"
        acquired = await session.scalar(text("SELECT GET_LOCK(:key, 10)"), {"key": key})
        if acquired != 1:
            raise AppError(503, "WRITE_BUSY", "写入繁忙，请稍后重试")

        async def release(connection):
            released = await connection.scalar(text("SELECT RELEASE_LOCK(:key)"), {"key": key})
            if released != 1:
                raise AppError(503, "LOCK_RELEASE_FAILED", "数据库暂不可用")
            # RELEASE_LOCK 与事务无关；只结束释放查询产生的只读事务。
            await connection.rollback()

        session.info.setdefault("connection_finalizers", []).append(release)
    elif connection.dialect.name == "sqlite":
        await session.execute(text("BEGIN IMMEDIATE"))
    session.info["watchlist_lock"] = True
