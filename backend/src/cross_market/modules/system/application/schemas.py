from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ComponentStatus(BaseModel):
    status: Literal["healthy", "unhealthy", "stale", "unknown"]
    detail: str | None = None


class Components(BaseModel):
    api: ComponentStatus
    mysql: ComponentStatus
    redis: ComponentStatus
    worker: ComponentStatus


class TaskStatus(BaseModel):
    name: str
    status: Literal[
        "disabled", "waiting", "idle", "success", "partial", "error", "stale", "unknown"
    ] = "disabled"
    detail: str
    last_success_at: datetime | None = None
    checked_at: datetime | None = None
    symbol_count: int | None = None


class SystemStatus(BaseModel):
    status: Literal["healthy", "degraded", "unhealthy"]
    checked_at: datetime
    version: str
    components: Components
    tasks: list[TaskStatus]
    market_data_enabled: bool = False


class ModuleInfo(BaseModel):
    name: str
    label: str
    tier: Literal["A", "B", "C"]
    status: Literal["foundation", "planned"]
    description: str


class ModulesResponse(BaseModel):
    modules: list[ModuleInfo]
