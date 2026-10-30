from model import Order, Status
from orders import can_cancel, next_status


def check_order(o: Order) -> list[str]:
    """What is wrong with an order."""
    errors = []
    if not o.lines:
        errors.append("no lines")
    if o.shipping < 0:
        errors.append("negative shipping")
    if any(l.unit_price <= 0 for l in o.lines):
        errors.append("bad price")
    if any(l.qty <= 0 for l in o.lines):
        errors.append("bad quantity")
    return errors


def valid_step(start: Status, to: Status) -> bool:
    """True when an order may go from one status to another."""
    if to == Status.CANCELLED:
        return can_cancel(start)
    return start != to and next_status(start) == to
