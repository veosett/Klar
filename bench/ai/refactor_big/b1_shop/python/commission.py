from model import Order
from money import round2
from orders import grand_total


def commission_rate(total: float) -> float:
    """The share an agent earns on a sale."""
    if total >= 1000.0:
        return 0.08
    if total >= 100.0:
        return 0.05
    return 0.02


def commission(total: float) -> float:
    """The agent's money for a sale."""
    return round2(total * commission_rate(total))


def commission_total(os: list[Order]) -> float:
    """The agent's money over several orders."""
    return sum(commission(grand_total(o)) for o in os)


def earned_bonus(amount: float) -> bool:
    """True when an agent earned the monthly bonus: 250.00 in commission."""
    return amount >= 250.0
