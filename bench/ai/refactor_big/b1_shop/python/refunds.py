from model import Order, Status
from money import fmt, round2
from orders import grand_total

REFUND_SHARES = {
    Status.DRAFT: 0.0,
    Status.PAID: 1.0,
    Status.PACKED: 1.0,
    Status.SHIPPED: 0.95,
    Status.DELIVERED: 0.9,
    Status.CANCELLED: 0.0,
}


def refund_share(s: Status) -> float:
    """The share of the money that comes back."""
    return REFUND_SHARES[s]


def refund_amount(o: Order) -> float:
    """The money that comes back for an order."""
    return round2(grand_total(o) * refund_share(o.status))


def refund_note(o: Order) -> str:
    """A line for the customer."""
    return f"Refund {fmt(refund_amount(o))} for order {o.id}"


def return_fee(amount: float) -> float:
    """The fee for sending goods back: 3.50 below 20.00, otherwise free."""
    if amount < 20.0:
        return 3.5
    return 0.0
