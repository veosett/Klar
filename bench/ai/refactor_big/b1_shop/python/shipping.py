from model import Tier
from money import fmt, round2

FREE_OVER = 50.0  # baskets from this amount ship free


def shipping_cost(amount: float, weight: float) -> float:
    """The cost of sending a parcel."""
    if amount >= FREE_OVER:
        return 0.0
    return round2(4.99 + weight * 1.5)


def member_cost(cost: float, t: Tier) -> float:
    """The cost for a member: gold members pay half."""
    if t == Tier.GOLD:
        return round2(cost * 0.5)
    return cost


SURCHARGES = {"Harbour": 7.5, "Summit": 12.0}


def surcharge(city: str) -> float:
    """A surcharge for hard to reach places."""
    return SURCHARGES.get(city, 0.0)


def shipping_label(cost: float) -> str:
    """The shipping line of a receipt."""
    if cost == 0:
        return "free shipping"
    return f"shipping {fmt(cost)}"
