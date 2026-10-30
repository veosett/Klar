from model import Order
from money import pct
from orders import grand_total


def commission_rate(total: int) -> float:
    """The share an agent earns on a sale."""
    if total >= 100000:
        return 0.08
    if total >= 10000:
        return 0.05
    return 0.02


def commission(total: int) -> int:
    """The agent's money for a sale."""
    return pct(total, commission_rate(total))


def commission_total(os: list[Order]) -> int:
    """The agent's money over several orders."""
    return sum(commission(grand_total(o)) for o in os)


def earned_bonus(amount: int) -> bool:
    """True when an agent earned the monthly bonus: 250.00 in commission."""
    return amount >= 25000
