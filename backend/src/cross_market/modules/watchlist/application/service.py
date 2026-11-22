from sqlalchemy import select

from cross_market.modules.securities.application.service import get_securities, get_security
from cross_market.modules.watchlist.application.schemas import GroupDTO, ItemDTO
from cross_market.modules.watchlist.infrastructure.locking import lock_watchlist
from cross_market.modules.watchlist.infrastructure.models import WatchlistGroup, WatchlistItem
from cross_market.shared.exceptions import AppError


async def list_quote_targets(session, limit=50) -> list[str]:
    if not 1 <= limit <= 50:
        raise ValueError("报价目标数量必须在1至50之间")
    ids = list(
        await session.scalars(
            select(WatchlistItem.security_id)
            .distinct()
            .order_by(WatchlistItem.security_id)
            .limit(limit)
        )
    )
    securities = await get_securities(session, ids)
    return list(dict.fromkeys(securities[key].symbol for key in ids if key in securities))


async def groups(session, *, lock=False):
    if lock:
        await lock_watchlist(session)
    statement = select(WatchlistGroup).order_by(WatchlistGroup.position, WatchlistGroup.id)
    if lock:
        statement = statement.with_for_update()
    return list(await session.scalars(statement))


async def group(session, group_id):
    row = await session.get(WatchlistGroup, group_id)
    if row is None:
        raise AppError(404, "GROUP_NOT_FOUND", "分组不存在")
    return row


async def items(session, group_id):
    return list(
        await session.scalars(
            select(WatchlistItem)
            .where(WatchlistItem.group_id == group_id)
            .order_by(WatchlistItem.position, WatchlistItem.id)
        )
    )


async def item(session, item_id):
    row = await session.get(WatchlistItem, item_id)
    if row is None:
        raise AppError(404, "WATCHLIST_NOT_FOUND", "自选条目不存在")
    return row


async def serialize(session, rows):
    securities = await get_securities(session, [row.security_id for row in rows])
    return [
        ItemDTO(
            id=row.id,
            group_id=row.group_id,
            security_id=row.security_id,
            position=row.position,
            note=row.note,
            security=securities[row.security_id],
        )
        for row in rows
    ]


def reorder(rows, ids):
    if len(ids) != len(set(ids)) or set(ids) != {row.id for row in rows}:
        raise AppError(422, "INVALID_ORDER", "排序必须完整且不重复地包含当前全部 ID")
    positions = {identifier: position for position, identifier in enumerate(ids)}
    for row in rows:
        row.position = positions[row.id]


def compact(rows):
    for position, row in enumerate(rows):
        row.position = position


def capacity(rows, maximum):
    if len(rows) >= maximum:
        raise AppError(409, "CAPACITY_EXCEEDED", "已达到数量上限")


async def list_groups(session):
    return {"groups": [GroupDTO.model_validate(row) for row in await groups(session)]}


async def create_group(session, body):
    rows = await groups(session, lock=True)
    capacity(rows, 50)
    row = WatchlistGroup(name=body.name, position=len(rows))
    session.add(row)
    await session.flush()
    return GroupDTO.model_validate(row)


async def order_groups(session, body):
    rows = await groups(session, lock=True)
    reorder(rows, body.ids)
    await session.flush()
    return {
        "groups": [GroupDTO.model_validate(row) for row in sorted(rows, key=lambda r: r.position)]
    }


async def update_group(session, group_id, body):
    await groups(session, lock=True)
    row = await group(session, group_id)
    row.name = body.name
    await session.flush()
    return GroupDTO.model_validate(row)


async def delete_group(session, group_id):
    rows = await groups(session, lock=True)
    row = await group(session, group_id)
    if await items(session, group_id):
        raise AppError(409, "GROUP_NOT_EMPTY", "请先移除分组成员")
    await session.delete(row)
    compact([other for other in rows if other.id != group_id])
    await session.flush()


async def list_items(session, group_id):
    await group(session, group_id)
    return {"items": await serialize(session, await items(session, group_id))}


async def create_item(session, body):
    await groups(session, lock=True)
    await group(session, body.group_id)
    await get_security(session, body.security_id)
    rows = await items(session, body.group_id)
    capacity(rows, 500)
    row = WatchlistItem(**body.model_dump(), position=len(rows))
    session.add(row)
    await session.flush()
    return (await serialize(session, [row]))[0]


async def order_items(session, body):
    await groups(session, lock=True)
    await group(session, body.group_id)
    rows = await items(session, body.group_id)
    reorder(rows, body.ids)
    await session.flush()
    return {"items": await serialize(session, sorted(rows, key=lambda row: row.position))}


async def update_item(session, item_id, body):
    await groups(session, lock=True)
    row = await item(session, item_id)
    row.note = body.note
    await session.flush()
    return (await serialize(session, [row]))[0]


async def delete_item(session, item_id):
    await groups(session, lock=True)
    row = await item(session, item_id)
    rows = await items(session, row.group_id)
    await session.delete(row)
    compact([other for other in rows if other.id != item_id])
    await session.flush()


async def move_item(session, item_id, body):
    await groups(session, lock=True)
    row = await item(session, item_id)
    await group(session, body.group_id)
    source = await items(session, row.group_id)
    target = source if row.group_id == body.group_id else await items(session, body.group_id)
    if row.group_id != body.group_id:
        capacity(target, 500)
        if any(other.security_id == row.security_id for other in target):
            raise AppError(409, "CONFLICT", "目标分组已包含此证券")
    remaining = [other for other in target if other.id != item_id]
    position = len(remaining) if body.position is None else body.position
    if position > len(remaining):
        raise AppError(422, "INVALID_POSITION", "位置超出分组范围")
    compact([other for other in source if other.id != item_id])
    row.group_id = body.group_id
    remaining.insert(position, row)
    compact(remaining)
    await session.flush()
    return (await serialize(session, [row]))[0]
