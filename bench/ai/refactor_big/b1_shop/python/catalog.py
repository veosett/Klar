from model import Category, Product
from money import fmt, round2


def price_band(p: Product) -> str:
    """How a product is shelved."""
    if p.price < 10.0:
        return "cheap"
    if p.price < 100.0:
        return "regular"
    return "premium"


def sale_price(p: Product, off: float) -> float:
    """The price after taking off a share of it."""
    return round2(p.price - p.price * off)


def stock_value(p: Product) -> float:
    """The value of the stock of a product."""
    return p.price * p.stock


def catalog_value(ps: list[Product]) -> float:
    """The value of all the stock."""
    return sum(stock_value(p) for p in ps)


def average_price(ps: list[Product]) -> float:
    """The average price, or nothing for no products."""
    if not ps:
        return 0.0
    return round2(sum(p.price for p in ps) / len(ps))


def most_expensive(ps: list[Product]) -> Product | None:
    """The dearest product."""
    return max(ps, key=lambda p: p.price, default=None)


def within_budget(ps: list[Product], budget: float) -> list[Product]:
    """Products one can buy with a budget."""
    return [p for p in ps if p.price <= budget]


def price_label(p: Product) -> str:
    """A shelf label."""
    return f"{p.name}: {fmt(p.price)}"


def is_gift(p: Product) -> bool:
    """True when a product counts as a gift: not food, and under 25.00."""
    return p.category != Category.FOOD and p.price < 25.0


def in_category(ps: list[Product], c: Category) -> list[Product]:
    """Products of one category, dearest first."""
    return sorted((p for p in ps if p.category == c), key=lambda p: -p.price)
