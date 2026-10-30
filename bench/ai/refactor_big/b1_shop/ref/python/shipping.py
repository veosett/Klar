from model import Tier
from money import fmt, pct

FREE_OVER = 5000  # baskets from this amount ship free


def shipping_cost(amount: int, weight: float) -> int:
    """The cost of sending a parcel."""
    if amount >= FREE_OVER:
        return 0
    return 499 + pct(150, weight)


def member_cost(cost: int, t: Tier) -> int:
    """The cost for a member: gold members pay half."""
    if t == Tier.GOLD:
        return pct(cost, 0.5)
    return cost


SURCHARGES = {"Harbour": 750, "Summit": 1200}


def surcharge(city: str) -> int:
    """A surcharge for hard to reach places."""
    return SURCHARGES.get(city, 0)


def shipping_label(cost: int) -> str:
    """The shipping line of a receipt."""
    if cost == 0:
        return "free shipping"
    return f"shipping {fmt(cost)}"
