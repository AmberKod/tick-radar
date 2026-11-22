import asyncio
import re
from datetime import UTC, datetime

import httpx

from cross_market.modules.market_data.domain.quotes import provider_symbol


class ProviderFailure(Exception):
    def __init__(self, code: str):
        self.code = code


class TencentSource:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    async def fetch(self, symbols: list[str]) -> tuple[dict[str, str], datetime]:
        if not 1 <= len(symbols) <= 50:
            raise ValueError("单次请求必须包含1至50个代码")
        keys = {provider_symbol(symbol) for symbol in symbols}
        try:
            async with asyncio.timeout(6):
                async with self.client.stream(
                    "GET",
                    "https://qt.gtimg.cn/",
                    params={"q": ",".join(sorted(keys))},
                    timeout=httpx.Timeout(6, connect=2),
                    follow_redirects=False,
                ) as response:
                    if response.status_code != 200:
                        raise ProviderFailure(
                            "PROVIDER_RATE_LIMIT"
                            if response.status_code == 429
                            else "PROVIDER_HTTP_ERROR"
                        )
                    payload = bytearray()
                    async for chunk in response.aiter_bytes():
                        payload.extend(chunk)
                        if len(payload) > 256 * 1024:
                            raise ProviderFailure("PROVIDER_BODY_TOO_LARGE")
                    received_at = datetime.now(UTC)
            text = payload.decode("gb18030")
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise ProviderFailure("PROVIDER_TIMEOUT") from exc
        except (httpx.HTTPError, UnicodeError) as exc:
            raise ProviderFailure("PROVIDER_UNAVAILABLE") from exc
        records = {}
        duplicates = set()
        for match in re.finditer(
            r'(?:^|(?<=[;\r\n]))\s*v_([A-Za-z0-9.-]+)="([^"\r\n]*)"\s*;', text
        ):
            key, raw = match.groups()
            if key in keys:
                if key in records:
                    duplicates.add(key)
                records[key] = raw
        for key in duplicates:
            records.pop(key, None)
        return records, received_at
