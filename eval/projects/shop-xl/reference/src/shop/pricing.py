from typing import Optional

from .errors import InvalidCode


def apply_discount(subtotal_cents: int, code: Optional[str]) -> int:
    if not code:
        return 0
    code = code.upper()
    if code == "SAVE10":
        return subtotal_cents // 10
    if code == "FLAT500":
        return min(500, subtotal_cents)
    raise InvalidCode(code)


LOYALTY_PERCENT = {"gold": 5, "silver": 2, "bronze": 0}


def loyalty_discount(amount_cents: int, tier: str) -> int:
    if tier not in LOYALTY_PERCENT:
        raise ValueError(f"unknown tier {tier}")
    return amount_cents * LOYALTY_PERCENT[tier] // 100
