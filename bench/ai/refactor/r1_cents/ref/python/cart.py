from dataclasses import dataclass, replace

from catalog import Item
from money import round_div

# Minimum amount (after discount, before tax) for free shipping: $50.00 (5000 cents).
FREE_SHIPPING_MIN: int = 5000


@dataclass(frozen=True)
class Line:
    item: Item
    qty: int


@dataclass(frozen=True)
class Cart:
    lines: tuple[Line, ...]
    code: str | None


def new_cart() -> Cart:
    return Cart(lines=(), code=None)


def add_line(cart: Cart, item: Item, qty: int) -> Cart:
    if qty < 1 or qty > 99:
        raise ValueError(f"invalid quantity: {qty}")
    return replace(cart, lines=cart.lines + (Line(item=item, qty=qty),))


def discount_percent(code: str) -> int | None:
    """Percentage taken off by a discount code, None for an unknown code."""
    return {"SAVE10": 10, "WELCOME5": 5, "VIP15": 15, "HALF": 50}.get(code)


def apply_code(cart: Cart, code: str) -> Cart:
    if discount_percent(code) is None:
        raise ValueError(f"unknown code: {code}")
    return replace(cart, code=code)


def item_count(cart: Cart) -> int:
    return sum(l.qty for l in cart.lines)


def line_total(line: Line) -> int:
    return line.item.price_cents * line.qty


def largest_line(cart: Cart) -> Line | None:
    return max(cart.lines, key=line_total, default=None)


def subtotal(cart: Cart) -> int:
    acc = 0
    for l in cart.lines:
        acc = acc + line_total(l)
    return acc


def discount(cart: Cart) -> int:
    """The discount for the cart's code, rounded to the cent (0 without a code)."""
    percent = 0 if cart.code is None else (discount_percent(cart.code) or 0)
    return round_div(subtotal(cart) * percent, 100)


def tax(cart: Cart, rate_bp: int) -> int:
    """Tax on the subtotal after the discount; the rate is in basis points (825 = 8.25%)."""
    taxable = subtotal(cart) - discount(cart)
    return round_div(taxable * rate_bp, 10000)


def total(cart: Cart, rate_bp: int) -> int:
    return subtotal(cart) - discount(cart) + tax(cart, rate_bp)


def free_shipping_gap(cart: Cart) -> int:
    """How much more must be bought (after discount) to get free shipping."""
    net = subtotal(cart) - discount(cart)
    if net >= FREE_SHIPPING_MIN:
        return 0
    return FREE_SHIPPING_MIN - net
