from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, Decimal, localcontext

UNIT = Decimal("0.00000001")
MAXIMUM = Decimal("999999999999999999999999.99999999")
ZERO = Decimal(0)


class ReplayError(ValueError):
    pass


def money(value):
    if not value.is_finite() or value.copy_abs() > MAXIMUM:
        raise ReplayError("金额超出存储范围")
    with localcontext() as context:
        context.prec = 80
        result = value.quantize(UNIT, rounding=ROUND_HALF_EVEN)
        if result.copy_abs() > MAXIMUM:
            raise ReplayError("金额超出存储范围")
        return result.copy_abs() if result == 0 else result


def formatted(value):
    with localcontext() as context:
        context.prec = 80
        return format(money(value), ".8f")


@dataclass
class Fact:
    kind: str
    security_id: str | None = None
    quantity: Decimal = ZERO
    price: Decimal = ZERO
    amount: Decimal = ZERO
    fee: Decimal = ZERO
    tax: Decimal = ZERO


@dataclass
class Position:
    quantity: Decimal = ZERO
    total_cost: Decimal = ZERO
    realized_pnl: Decimal = ZERO
    dividend_income: Decimal = ZERO

    @property
    def average_cost(self):
        with localcontext() as context:
            context.prec = 80
            return money(self.total_cost / self.quantity) if self.quantity else ZERO


@dataclass
class Result:
    cash_balance: Decimal = ZERO
    realized_pnl: Decimal = ZERO
    dividend_income: Decimal = ZERO
    standalone_fees: Decimal = ZERO
    external_net_flow: Decimal = ZERO
    internal_net_flow: Decimal = ZERO
    positions: dict[str, Position] = field(default_factory=dict)

    @property
    def total_cost(self):
        with localcontext() as context:
            context.prec = 80
            return money(sum((p.total_cost for p in self.positions.values()), ZERO))


def amounts(fact):
    with localcontext() as context:
        context.prec = 80
        gross = money(fact.quantity * fact.price) if fact.kind in {"BUY", "SELL"} else fact.amount
        if fact.kind == "BUY":
            cash = -(gross + fact.fee + fact.tax)
        elif fact.kind in {"SELL", "DIVIDEND"}:
            cash = gross - fact.fee - fact.tax
        elif fact.kind == "TRANSFER_OUT":
            cash = -(gross + fact.fee)
        elif fact.kind in {"WITHDRAWAL", "FEE"}:
            cash = -gross
        else:
            cash = gross
        return money(gross), money(cash)


def replay(facts):
    result = Result()
    with localcontext() as context:
        context.prec = 80
        for fact in facts:
            gross, cash = amounts(fact)
            position = (
                result.positions.setdefault(fact.security_id, Position())
                if fact.security_id
                else None
            )
            if fact.kind == "BUY":
                position.quantity += fact.quantity
                position.total_cost = money(position.total_cost - cash)
            elif fact.kind == "SELL":
                if fact.quantity > position.quantity:
                    raise ReplayError("卖出数量超过持仓")
                removed = (
                    position.total_cost
                    if fact.quantity == position.quantity
                    else money(position.total_cost * fact.quantity / position.quantity)
                )
                position.quantity -= fact.quantity
                position.total_cost = money(position.total_cost - removed)
                profit = money(cash - removed)
                position.realized_pnl = money(position.realized_pnl + profit)
                result.realized_pnl = money(result.realized_pnl + profit)
            elif fact.kind == "DIVIDEND":
                position.dividend_income = money(position.dividend_income + cash)
                result.dividend_income = money(result.dividend_income + cash)
            elif fact.kind == "FEE":
                result.standalone_fees = money(result.standalone_fees + gross)
            elif fact.kind in {"TRANSFER_OUT", "TRANSFER_IN"}:
                principal = -gross if fact.kind == "TRANSFER_OUT" else gross
                result.internal_net_flow = money(result.internal_net_flow + principal)
                if fact.kind == "TRANSFER_OUT":
                    result.standalone_fees = money(result.standalone_fees + fact.fee)
            elif fact.kind in {"DEPOSIT", "WITHDRAWAL"}:
                result.external_net_flow = money(result.external_net_flow + cash)
            result.cash_balance = money(result.cash_balance + cash)
            if result.cash_balance < 0:
                raise ReplayError("现金余额不足")
            if position is not None:
                if position.quantity > Decimal("9999999999999999.99999999"):
                    raise ReplayError("累计持仓数量超出16位整数及8位小数范围")
                money(position.quantity)
            money(result.total_cost)
    return result
