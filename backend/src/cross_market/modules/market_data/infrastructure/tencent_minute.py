import asyncio
import json
import re
from datetime import UTC, datetime
from decimal import Decimal
from time import monotonic
from zoneinfo import ZoneInfo

import httpx

from cross_market.modules.market_data.application.minute_schemas import MinuteBar


class MinuteSourceFailure(Exception):
    pass


def parse_bars(payload: bytes, provider: str) -> list[MinuteBar]:
    try:
        def reject_constant(value):
            raise ValueError("非标准JSON常量")

        document = json.loads(payload.decode("utf-8-sig"), parse_constant=reject_constant)
        if not isinstance(document, dict) or type(document.get("code")) is not int:
            raise ValueError("分钟响应无效")
        if document["code"] != 0 or not isinstance(document["data"][provider], dict):
            raise ValueError("分钟证券身份不匹配")
        rows = document["data"][provider]["m15"]
        if not isinstance(rows, list) or len(rows) > 320:
            raise ValueError("分钟条数无效")
        bars = []
        previous = None
        for row in rows:
            if not isinstance(row, list) or not 6 <= len(row) <= 32:
                raise ValueError("分钟字段无效")
            raw, opening, closing, high, low, volume = row[:6]
            if any(not isinstance(value, str) or not 1 <= len(value) <= 64 for value in row[:6]):
                raise ValueError("分钟字段必须为字符串")
            if not re.fullmatch(r"[0-9]{12}", raw):
                raise ValueError("分钟时间格式无效")
            local = datetime.strptime(raw, "%Y%m%d%H%M").replace(tzinfo=ZoneInfo("Asia/Shanghai"))
            clock = local.hour * 60 + local.minute
            if local.minute % 15 or not (585 <= clock <= 690 or 795 <= clock <= 900):
                raise ValueError("分钟时间不在已验证时段")
            timestamp = local.astimezone(UTC)
            if previous is not None and timestamp <= previous:
                raise ValueError("分钟时间必须严格升序")
            if any(not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value) for value in row[1:6]):
                raise ValueError("分钟数值格式无效")
            o, c, h, low_value, v = (Decimal(value) for value in row[1:6])
            if any(not value.is_finite() or value <= 0 for value in (o, c, h, low_value)):
                raise ValueError("分钟价格无效")
            if not v.is_finite() or v < 0 or not low_value <= min(o, c) <= max(o, c) <= h:
                raise ValueError("分钟价格范围或成交量无效")
            bars.append(MinuteBar(
                timestamp=timestamp, source_time_raw=raw, open=opening, close=closing,
                high=high, low=low, volume=volume,
            ))
            previous = timestamp
        return bars
    except (ValueError, KeyError, TypeError, AttributeError, UnicodeError) as exc:
        raise MinuteSourceFailure from exc


class TencentMinuteSource:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client
        self._budget_window = -1
        self._budget_count = 0

    async def fetch(self, provider: str) -> list[MinuteBar]:
        window = int(monotonic() // 60)
        if self._budget_window != window:
            self._budget_window, self._budget_count = window, 0
        if self._budget_count >= 30:
            raise MinuteSourceFailure
        self._budget_count += 1
        try:
            async with asyncio.timeout(6):
                async with self.client.stream(
                    "GET", "https://ifzq.gtimg.cn/appstock/app/kline/mkline",
                    params={"param": f"{provider},m15,,320"},
                    timeout=httpx.Timeout(6, connect=2), follow_redirects=False,
                ) as response:
                    if response.status_code != 200:
                        raise MinuteSourceFailure
                    payload = bytearray()
                    async for chunk in response.aiter_bytes():
                        payload.extend(chunk)
                        if len(payload) > 2 * 1024 * 1024:
                            raise MinuteSourceFailure
            return parse_bars(bytes(payload), provider)
        except (TimeoutError, httpx.HTTPError) as exc:
            raise MinuteSourceFailure from exc
