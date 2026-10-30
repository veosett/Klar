from model import Customer, Order, Status
from money import fmt
from orders import grand_total


def message_for(o: Order, c: Customer) -> str:
    """What the customer is told about an order."""
    who = c.name
    if o.status == Status.DRAFT:
        return f"{who}, your order {o.id} is not paid yet"
    if o.status == Status.PAID:
        return f"{who}, we received {fmt(grand_total(o))} for order {o.id}"
    if o.status == Status.PACKED:
        return f"{who}, your order {o.id} is packed"
    if o.status == Status.SHIPPED:
        return f"{who}, your order {o.id} is on its way"
    if o.status == Status.DELIVERED:
        return f"{who}, your order {o.id} arrived"
    return f"{who}, your order {o.id} was cancelled"


def reminder(c: Customer, amount: float) -> str:
    """A reminder to pay."""
    return f"{c.name}: please pay {fmt(amount)}"


def should_notify(s: Status) -> bool:
    """True when the customer should get a message."""
    return s != Status.DRAFT
