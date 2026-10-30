from model import Category, Line, Order, Product, Status
from money import fmt, round2
from orders import line_total


def rate_for(c: Category) -> float:
    """The tax rate of a category."""
    match c:
        case Category.BOOK:
            return 0.0
        case Category.FOOD:
            return 0.05
        case Category.TOY | Category.TOOL:
            return 0.2
        case Category.GARDEN:
            return 0.1


def category_of(sku: str, ps: list[Product]) -> Category:
    for p in ps:
        if p.sku == sku:
            return p.category
    return Category.BOOK


def line_tax(l: Line, ps: list[Product]) -> float:
    """The tax of one line."""
    rate = rate_for(category_of(l.sku, ps))
    return round2(line_total(l) * rate)


def order_tax(o: Order, ps: list[Product]) -> float:
    """The tax of an order: nothing until it is paid, nothing when cancelled."""
    if not taxable(o.status):
        return 0.0
    return sum(line_tax(l, ps) for l in o.lines)


def taxable(s: Status) -> bool:
    """True when the order owes tax."""
    return s not in (Status.DRAFT, Status.CANCELLED)


def tax_note(t: float) -> str:
    """The tax line of a receipt."""
    if t == 0:
        return "tax free"
    return f"tax {fmt(t)}"
