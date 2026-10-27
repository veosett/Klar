from cart import (Cart, Line, discount, free_shipping_gap, item_count,
                  line_total, subtotal, tax, total)
from money import format_amount


def line_text(line: Line) -> str:
    """Text of one line, e.g. 2 x Widget @ $3.50 = $7.00."""
    return f"{line.qty} x {line.item.name} @ {format_amount(line.item.price)} = {format_amount(line_total(line))}"


def render(cart: Cart, rate_bp: int) -> str:
    lines = [line_text(l) for l in cart.lines]
    lines.append(f"Subtotal: {format_amount(subtotal(cart))}")
    if cart.code is not None:
        lines.append(f"Discount ({cart.code}): -{format_amount(discount(cart))}")
    lines.append(f"Tax: {format_amount(tax(cart, rate_bp))}")
    lines.append(f"Total: {format_amount(total(cart, rate_bp))}")
    gap = free_shipping_gap(cart)
    if gap > 0.0:
        lines.append(f"Add {format_amount(gap)} more for free shipping")
    else:
        lines.append("Free shipping")
    return "\n".join(lines)


def summary(cart: Cart, rate_bp: int) -> str:
    """One-line summary, e.g. 3 items, total $19.00."""
    n = item_count(cart)
    noun = "item" if n == 1 else "items"
    return f"{n} {noun}, total {format_amount(total(cart, rate_bp))}"
