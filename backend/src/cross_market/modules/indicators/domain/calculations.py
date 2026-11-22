from dataclasses import dataclass, fields
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal, localcontext


@dataclass(frozen=True)
class Bar:
    day: date
    high: Decimal
    low: Decimal
    close: Decimal


@dataclass(frozen=True)
class Params:
    ma_period: int = 10
    macd_fast: int = 6
    macd_slow: int = 13
    macd_signal: int = 5
    kdj_lookback: int = 13
    kdj_k: int = 5
    kdj_d: int = 5
    atr_period: int = 14

    def __post_init__(self):
        bounds = {
            "ma_period": (2, 120),
            "macd_fast": (2, 60),
            "macd_slow": (3, 120),
            "macd_signal": (2, 60),
            "kdj_lookback": (2, 120),
            "kdj_k": (2, 60),
            "kdj_d": (2, 60),
            "atr_period": (2, 120),
        }
        for name, (minimum, maximum) in bounds.items():
            value = getattr(self, name)
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError(f"指标参数无效：{name}")
        if self.macd_fast >= self.macd_slow:
            raise ValueError("macd_fast必须小于macd_slow")


@dataclass(frozen=True)
class Point:
    date: date
    ma: str | None
    dif: str | None
    dea: str | None
    macd: str | None
    k: str | None
    d: str | None
    j: str | None
    atr: str | None


def _ema(values: list[Decimal], period: int) -> list[Decimal | None]:
    result: list[Decimal | None] = [None] * len(values)
    if len(values) >= period:
        current = sum(values[:period], Decimal(0)) / period
        result[period - 1] = current
        alpha = Decimal(2) / (period + 1)
        for index in range(period, len(values)):
            current += alpha * (values[index] - current)
            result[index] = current
    return result


def _format(value: Decimal | None) -> str | None:
    if value is None:
        return None
    rounded = value.quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_EVEN)
    if rounded.is_zero():
        rounded = abs(rounded)
    return format(rounded, "f")


def calculate_daily(bars: list[Bar], parameters: Params = Params()) -> list[Point]:
    # 即使调用方绕开dataclass构造，也在领域入口校验参数。
    Params(**{field.name: getattr(parameters, field.name) for field in fields(Params)})
    previous_day = None
    for bar in bars:
        if type(bar.day) is not date or (previous_day is not None and bar.day <= previous_day):
            raise ValueError("日线日期必须严格升序")
        for value in (bar.high, bar.low, bar.close):
            if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
                raise ValueError("日线价格必须为有限正Decimal")
        if not bar.low <= bar.close <= bar.high:
            raise ValueError("日线价格范围无效")
        previous_day = bar.day
    with localcontext() as context:
        context.prec = 80
        context.rounding = ROUND_HALF_EVEN
        closes = [bar.close for bar in bars]
        fast = _ema(closes, parameters.macd_fast)
        slow = _ema(closes, parameters.macd_slow)
        difs = [a - b for a, b in zip(fast, slow, strict=True) if a is not None and b is not None]
        deas = _ema(difs, parameters.macd_signal)
        result = []
        previous_k = previous_d = Decimal(50)
        trs: list[Decimal] = []
        previous_atr = None
        for index, bar in enumerate(bars):
            ma = None
            if index >= parameters.ma_period - 1:
                ma = sum(closes[index + 1 - parameters.ma_period : index + 1], Decimal(0))
                ma /= parameters.ma_period
            dif = dea = macd = None
            offset = index - parameters.macd_slow + 1
            if offset >= 0:
                dif = difs[offset]
                dea = deas[offset]
                if dea is not None:
                    macd = 2 * (dif - dea)
            k = d = j = None
            if index >= parameters.kdj_lookback - 1:
                window = bars[index + 1 - parameters.kdj_lookback : index + 1]
                high, low = max(item.high for item in window), min(item.low for item in window)
                rsv = Decimal(50) if high == low else (bar.close - low) / (high - low) * 100
                k = ((parameters.kdj_k - 1) * previous_k + rsv) / parameters.kdj_k
                d = ((parameters.kdj_d - 1) * previous_d + k) / parameters.kdj_d
                j = 3 * k - 2 * d
                previous_k, previous_d = k, d
            tr = bar.high - bar.low
            if index:
                tr = max(tr, abs(bar.high - closes[index - 1]), abs(bar.low - closes[index - 1]))
            trs.append(tr)
            if index == parameters.atr_period - 1:
                previous_atr = sum(trs, Decimal(0)) / parameters.atr_period
            elif index >= parameters.atr_period:
                previous_atr = (
                    (parameters.atr_period - 1) * previous_atr + tr
                ) / parameters.atr_period
            result.append(
                Point(
                    bar.day,
                    *(_format(value) for value in (ma, dif, dea, macd, k, d, j, previous_atr)),
                )
            )
        return result
