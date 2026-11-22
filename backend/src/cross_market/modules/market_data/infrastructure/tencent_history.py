import asyncio
import json
import re
from datetime import date
from decimal import Decimal
from time import monotonic

import httpx

from cross_market.modules.market_data.application.history_schemas import HistoryBar


class HistorySourceFailure(Exception):
    pass


def document_from_bytes(payload: bytes, provider: str) -> dict:
    try:
        try:
            text = payload.decode("utf-8-sig").strip()
        except UnicodeError:
            text = payload.decode("gb18030").strip()
        if not text.startswith("{"):
            prefix, separator, text = text.partition("=")
            if not separator or prefix.strip() != f"kline_day_{provider}":
                raise ValueError("历史响应包装无效")

        def reject_constant(value):
            raise ValueError("非标准JSON常量")

        document = json.loads(text.strip().removesuffix(";"), parse_constant=reject_constant)
        if not isinstance(document, dict) or type(document.get("code")) is not int:
            raise ValueError("历史响应无效")
        if document["code"] != 0:
            raise ValueError("历史数据源返回错误")
        if not isinstance(document["data"][provider], dict):
            raise ValueError("历史证券身份不匹配")
        return document
    except (ValueError, KeyError, TypeError, AttributeError, UnicodeError) as exc:
        raise HistorySourceFailure from exc


def parse_bars(
    payload: bytes, provider: str, adjustment: str, limit: int, *, end: date | None = None
) -> list[HistoryBar]:
    try:
        document = document_from_bytes(payload, provider)
        field = {"raw": "day", "qfq": "qfqday", "hfq": "hfqday"}[adjustment]
        rows = document["data"][provider][field]
        if not isinstance(rows, list) or len(rows) > limit:
            raise ValueError("历史记录数量无效")
        bars = []
        previous = None
        for row in rows:
            # 港美复权行附有公司行动等字段；仅前六项为OHLCV合同。
            if not isinstance(row, list) or not 6 <= len(row) <= 32:
                raise ValueError("历史记录字段无效")
            row = row[:6]
            if any(not isinstance(value, str) or not 1 <= len(value) <= 64 for value in row):
                raise ValueError("历史记录字符串无效")
            day = date.fromisoformat(row[0])
            if day.isoformat() != row[0] or (previous is not None and day <= previous):
                raise ValueError("历史日期顺序无效")
            if end is not None and day > end:
                raise ValueError("供应商未遵循历史截止日期")
            if any(not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value) for value in row[1:]):
                raise ValueError("历史数值格式无效")
            opening, closing, high, low, volume = (Decimal(value) for value in row[1:])
            if any(not value.is_finite() or value <= 0 for value in (opening, closing, high, low)):
                raise ValueError("历史价格无效")
            if not volume.is_finite() or volume < 0:
                raise ValueError("历史成交量无效")
            if low > min(opening, closing) or high < max(opening, closing):
                raise ValueError("历史高低价无效")
            bars.append(
                HistoryBar(
                    date=day, open=row[1], close=row[2], high=row[3], low=row[4], volume=row[5]
                )
            )
            previous = day
        return bars
    except (ValueError, KeyError, TypeError, AttributeError, UnicodeError) as exc:
        raise HistorySourceFailure from exc


class TencentHistorySource:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client
        self._identities: dict[str, tuple[float, str]] = {}
        self._budget_window = -1
        self._budget_count = 0

    async def _request(self, route: str, provider: str, mode: str, limit: int, end: date) -> bytes:
        # 单API进程历史请求预算独立于实时报价；每次身份探测也计入预算。
        window = int(monotonic() // 60)
        if self._budget_window != window:
            self._budget_window, self._budget_count = window, 0
        if self._budget_count >= 30:
            raise HistorySourceFailure
        self._budget_count += 1
        try:
            async with asyncio.timeout(6):
                async with self.client.stream(
                    "GET",
                    "https://web.ifzq.gtimg.cn/appstock/app/" + route,
                    params={"param": f"{provider},day,,{end.isoformat()},{limit},{mode}"},
                    timeout=httpx.Timeout(6, connect=2),
                    follow_redirects=False,
                ) as response:
                    if response.status_code != 200:
                        raise HistorySourceFailure
                    payload = bytearray()
                    async for chunk in response.aiter_bytes():
                        payload.extend(chunk)
                        if len(payload) > 2 * 1024 * 1024:
                            raise HistorySourceFailure
                    return bytes(payload)
        except (TimeoutError, httpx.HTTPError) as exc:
            raise HistorySourceFailure from exc

    async def _us_identity(self, provider: str, end: date) -> str:
        cached = self._identities.get(provider)
        if cached and monotonic() - cached[0] < 300:
            return cached[1]
        # 历史端点自带证券元信息。只用它确认后缀，不调用实时报价链路。
        body = await self._request("kline/kline", provider, "", 1, end)
        document = document_from_bytes(body, provider)
        try:
            metadata = document["data"][provider]["qt"][provider]
            actual = metadata[2]
            ticker = provider[2:]
            if actual not in {ticker + suffix for suffix in (".OQ", ".N", ".AM", ".A")}:
                raise ValueError("美股历史身份无法确认")
            qualified = "us" + actual
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise HistorySourceFailure from exc
        if len(self._identities) >= 64:
            self._identities.pop(next(iter(self._identities)))
        self._identities[provider] = (monotonic(), qualified)
        return qualified

    async def fetch(
        self, provider: str, adjustment: str, limit: int, *, end: date
    ) -> list[HistoryBar]:
        mode = "" if adjustment == "raw" else adjustment
        if provider.startswith("us"):
            if adjustment == "hfq":
                raise HistorySourceFailure
            provider = await self._us_identity(provider, end)
            route = "kline/kline" if adjustment == "raw" else "usfqkline/get"
        elif provider.startswith("hk"):
            route = "kline/kline" if adjustment == "raw" else "hkfqkline/get"
        else:
            route = "fqkline/get"
        payload = await self._request(route, provider, mode, limit, end)
        return parse_bars(payload, provider, adjustment, limit, end=end)
