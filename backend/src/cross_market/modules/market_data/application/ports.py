from datetime import datetime
from typing import Protocol


class QuoteSource(Protocol):
    async def fetch(self, symbols: list[str]) -> tuple[dict[str, str], datetime]: ...


class QuoteCache(Protocol):
    async def read(self, symbol: str) -> str | None: ...

    async def read_many(self, symbols: list[str]) -> list[str | None]: ...

    async def write(
        self,
        symbol: str,
        payload: str,
        owner: str | None = None,
        ttl: int = 3600,
        publication_guard: tuple[str, str] | None = None,
    ) -> bool: ...

    async def acquire(self, symbol: str) -> str | None: ...

    async def take_budget(self) -> bool: ...
