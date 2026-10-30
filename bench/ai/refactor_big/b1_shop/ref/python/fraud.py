from model import Customer, Order, Status, Tier
from orders import grand_total, item_count


def risk_score(o: Order, c: Customer) -> int:
    """How suspicious an order looks."""
    score = 0
    if grand_total(o) >= 100000:
        score += 3
    elif grand_total(o) >= 30000:
        score += 1
    if item_count(o) > 20:
        score += 1
    if c.tier == Tier.BASIC:
        score += 1
    return score


def needs_review(o: Order, c: Customer) -> bool:
    """True when fraud review should look at the order."""
    return is_reviewable(o.status) and risk_score(o, c) >= 3


def is_reviewable(s: Status) -> bool:
    """True when the order can still be stopped by a review."""
    return s in (Status.PAID, Status.ON_HOLD, Status.PACKED)
