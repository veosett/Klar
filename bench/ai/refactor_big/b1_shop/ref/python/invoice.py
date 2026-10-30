from model import Customer, Line, Order
from money import fmt
from orders import grand_total, line_total, subtotal


def header(o: Order, c: Customer) -> str:
    """The first line of an invoice."""
    return f"Invoice {o.id} for {c.first_name} {c.last_name}, {c.city}"


def line_text(l: Line) -> str:
    """One line of goods."""
    return f"  {l.qty} x {l.sku} @ {fmt(l.unit_price)} = {fmt(line_total(l))}"


def due_note(total: int) -> str:
    """How long the customer has to pay."""
    if total > 10000:
        return "payable in 30 days"
    return "payable in 14 days"


def invoice_text(o: Order, c: Customer) -> str:
    """A whole invoice."""
    rows = [line_text(l) for l in o.lines]
    tail = [
        f"goods: {fmt(subtotal(o))}",
        f"shipping: {fmt(o.shipping)}",
        f"total: {fmt(grand_total(o))}",
        due_note(grand_total(o)),
    ]
    return "\n".join([header(o, c), *rows, *tail])
