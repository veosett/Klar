from model import Tier
from money import round2


def tier_rate(t: Tier) -> float:
    """The share a tier takes off."""
    match t:
        case Tier.BASIC:
            return 0.0
        case Tier.SILVER:
            return 0.05
        case Tier.GOLD:
            return 0.1


def volume_rate(amount: float) -> float:
    """The share a large basket takes off."""
    if amount >= 500.0:
        return 0.1
    if amount >= 200.0:
        return 0.05
    return 0.0


def discount_for(amount: float, t: Tier) -> float:
    """The discount: the better of the tier and the basket."""
    rate = max(tier_rate(t), volume_rate(amount))
    return round2(amount * rate)


COUPONS = {"FIVE": 5.0, "TEN": 10.0}


def coupon_value(code: str, amount: float) -> float:
    """What a coupon takes off, never more than the basket."""
    return min(COUPONS.get(code, 0.0), amount)


def net_amount(amount: float, t: Tier, code: str) -> float:
    """The basket after the discount and the coupon."""
    return amount - discount_for(amount, t) - coupon_value(code, amount)
