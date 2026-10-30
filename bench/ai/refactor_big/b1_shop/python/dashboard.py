from analytics import revenue
from model import Order, Status
from money import fmt
from orders import grand_total, is_open, status_label


def all_statuses() -> list[Status]:
    """Every status, in the order the dashboard shows them."""
    return [Status.DRAFT, Status.PAID, Status.PACKED, Status.SHIPPED, Status.DELIVERED, Status.CANCELLED]


def status_counts(os: list[Order]) -> list[str]:
    """One line per status: "Paid: 3"."""
    return [f"{status_label(s)}: {sum(1 for o in os if o.status == s)}" for s in all_statuses()]


def status_color(s: Status) -> str:
    """The colour of a status on the board."""
    if s == Status.DRAFT:
        return "grey"
    if s in (Status.PAID, Status.PACKED):
        return "blue"
    if s in (Status.SHIPPED, Status.DELIVERED):
        return "green"
    return "red"


def open_value(os: list[Order]) -> float:
    """The money tied up in open orders."""
    return sum(grand_total(o) for o in os if is_open(o.status))


def headline(os: list[Order]) -> str:
    """The headline of the board."""
    return f"{len(os)} orders, {fmt(revenue(os))} received, {fmt(open_value(os))} open"


def value_alert(os: list[Order]) -> bool:
    """True when the board should flag the money tied up: over 5000.00."""
    return open_value(os) > 5000.0
