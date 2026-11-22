import hashlib
import json
import unicodedata
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import IntegrityError

from cross_market.modules.indicators.application.profile_schemas import ProfileResponse
from cross_market.modules.indicators.infrastructure.models import IndicatorProfile
from cross_market.shared.exceptions import AppError

TABLE = IndicatorProfile.__table__


def profile_values(body):
    values = body.model_dump(exclude={"version"})
    normalized = unicodedata.normalize("NFKC", body.name).casefold()
    values["name_key"] = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    values["algorithm_version"] = "daily-v1" if body.timeframe == "day" else "m15-v1"
    return values


def serialize(row):
    values = dict(row)
    values.pop("name_key")
    canonical = json.dumps(values["parameters"], sort_keys=True, separators=(",", ":"))
    values["parameter_hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    for key in ("created_at", "updated_at"):
        value = values[key]
        values[key] = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return ProfileResponse.model_validate(values)


def name_conflict(error):
    original = error.orig
    message = str(original)
    mysql_duplicate = getattr(original, "args", (None,))[0] == 1062
    sqlite_duplicate = "UNIQUE constraint failed: t_indicator_profile.name_key" in message
    return sqlite_duplicate or (mysql_duplicate and "uq_indicator_profile_name_key" in message)


async def execute_write(session, statement):
    try:
        return await session.execute(statement)
    except IntegrityError as error:
        if name_conflict(error):
            raise AppError(409, "PROFILE_NAME_CONFLICT", "指标配置名称已存在") from error
        raise


async def list_profiles(session):
    rows = (await session.execute(select(TABLE).order_by(TABLE.c.name_key, TABLE.c.id))).mappings()
    return {"items": [serialize(row) for row in rows]}


async def get_profile(session, profile_id):
    row = (await session.execute(select(TABLE).where(TABLE.c.id == profile_id))).mappings().first()
    if row is None:
        raise AppError(404, "PROFILE_NOT_FOUND", "指标配置不存在")
    return serialize(row)


async def create_profile(session, body):
    now = datetime.now(UTC)
    values = {
        **profile_values(body),
        "id": str(uuid4()),
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    await execute_write(session, insert(TABLE).values(**values))
    # 以实际持久化值响应，保持MySQL时间精度处理后的创建/读取结果一致。
    return await get_profile(session, values["id"])


async def version_failure(session, profile_id):
    exists = await session.scalar(
        select(TABLE.c.id).where(TABLE.c.id == profile_id).with_for_update()
    )
    if exists is None:
        raise AppError(404, "PROFILE_NOT_FOUND", "指标配置不存在")
    raise AppError(409, "PROFILE_VERSION_CONFLICT", "指标配置已变更，请重新加载")


async def update_profile(session, profile_id, body):
    result = await execute_write(
        session,
        update(TABLE)
        .where(TABLE.c.id == profile_id, TABLE.c.version == body.version)
        .values(**profile_values(body), version=body.version + 1, updated_at=datetime.now(UTC)),
    )
    if result.rowcount != 1:
        await version_failure(session, profile_id)
    return await get_profile(session, profile_id)


async def delete_profile(session, profile_id, version):
    result = await session.execute(
        delete(TABLE).where(TABLE.c.id == profile_id, TABLE.c.version == version)
    )
    if result.rowcount != 1:
        await version_failure(session, profile_id)
