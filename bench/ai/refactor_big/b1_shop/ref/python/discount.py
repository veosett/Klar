from model import Tier
from money import pct


def tier_rate(t: Tier) -> float:
    """The share a tier takes off."""
    match t:
        case Tier.BASIC:
            return 0.0
        case Tier.SILVER:
            return 0.05
        case Tier.GOLD:
            return 0.1


def volume_rate(amount: int) -> float:
    """The share a large basket takes off."""
    if amount >= 50000:
        return 0.1
    if amount >= 20000:
        return 0.05
    return 0.0


def discount_for(amount: int, t: Tier) -> int:
    """The discount: the better of the tier and the basket."""
    rate = max(tier_rate(t), volume_rate(amount))
    return pct(amount, rate)


COUPONS = {"FIVE": 500, "TEN": 1000}


def coupon_value(code: str, amount: int) -> int:
    """What a coupon takes off, never more than the basket."""
    return min(COUPONS.get(code, 0), amount)


def net_amount(amount: int, t: Tier, code: str) -> int:
    """The basket after the discount and the coupon."""
    return amount - discount_for(amount, t) - coupon_value(code, amount)
