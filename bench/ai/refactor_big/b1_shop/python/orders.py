from dataclasses import replace

from model import Line, Order, Status


def line_total(l: Line) -> float:
    """The price of one line."""
    return l.unit_price * l.qty


def subtotal(o: Order) -> float:
    """The goods of an order, without shipping."""
    return sum(line_total(l) for l in o.lines)


def grand_total(o: Order) -> float:
    """What the customer pays."""
    return subtotal(o) + o.shipping


def item_count(o: Order) -> int:
    """The number of items in an order."""
    return sum(l.qty for l in o.lines)


STATUS_LABELS = {
    Status.DRAFT: "Draft",
    Status.PAID: "Paid",
    Status.PACKED: "Packed",
    Status.SHIPPED: "Shipped",
    Status.DELIVERED: "Delivered",
    Status.CANCELLED: "Cancelled",
}


def status_label(s: Status) -> str:
    """The status as people read it."""
    return STATUS_LABELS[s]


def is_open(s: Status) -> bool:
    """True while there is still work to do on the order."""
    return s in (Status.DRAFT, Status.PAID, Status.PACKED, Status.SHIPPED)


def next_status(s: Status) -> Status:
    """The next step of an order."""
    match s:
        case Status.DRAFT:
            return Status.PAID
        case Status.PAID:
            return Status.PACKED
        case Status.PACKED:
            return Status.SHIPPED
        case Status.SHIPPED:
            return Status.DELIVERED
        case Status.DELIVERED:
            return Status.DELIVERED
        case Status.CANCELLED:
            return Status.CANCELLED


def can_cancel(s: Status) -> bool:
    """True while the customer can still cancel."""
    return s in (Status.DRAFT, Status.PAID)


def is_revenue(s: Status) -> bool:
    """True when money was received for the order."""
    return s not in (Status.DRAFT, Status.CANCELLED)


def advance(o: Order) -> Order:
    """The order one step further."""
    return replace(o, status=next_status(o.status))


def cancel(o: Order) -> Order:
    """The order cancelled, if that is still possible."""
    return replace(o, status=Status.CANCELLED) if can_cancel(o.status) else o
