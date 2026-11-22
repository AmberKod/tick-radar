"""将外部 UUID 统一为小写连字符格式，避免数据库排序规则影响身份比较。"""

from typing import Annotated
from uuid import UUID

from pydantic import BeforeValidator, WithJsonSchema


def canonical_uuid(value: str) -> str:
    return str(UUID(str(value).strip()))


EntityId = Annotated[
    str,
    BeforeValidator(canonical_uuid),
    WithJsonSchema({"type": "string", "format": "uuid"}),
]
