from model import Order, Product, Status
from money import plain
from orders import grand_total, status_label

STATUS_CODES = {
    Status.DRAFT: "D",
    Status.PAID: "P",
    Status.ON_HOLD: "H",
    Status.PACKED: "K",
    Status.SHIPPED: "S",
    Status.DELIVERED: "V",
    Status.CANCELLED: "X",
}


def status_code(s: Status) -> str:
    """A one-letter code for the warehouse system."""
    return STATUS_CODES[s]


def order_row(o: Order) -> str:
    """A row of the orders file."""
    return f"{o.id},{status_code(o.status)},{status_label(o.status)},{plain(grand_total(o))}"


def product_row(p: Product) -> str:
    """A row of the products file."""
    return f"{p.sku},{p.name},{plain(p.price)},{p.weight:.2f}"


def orders_file(os: list[Order]) -> str:
    """The orders file."""
    return "\n".join(["id,code,status,total", *(order_row(o) for o in os)])
