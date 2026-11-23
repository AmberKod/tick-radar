from decimal import ROUND_HALF_EVEN, Decimal, localcontext


def implied_rate(source_amount, target_amount):
    with localcontext() as context:
        context.prec = 80
        return format(
            (Decimal(target_amount) / Decimal(source_amount)).quantize(
                Decimal("0.000000000001"), rounding=ROUND_HALF_EVEN
            ),
            ".12f",
        )
