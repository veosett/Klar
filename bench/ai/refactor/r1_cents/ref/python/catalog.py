from dataclasses import dataclass

from money import format_amount


@dataclass(frozen=True)
class Item:
    name: str
    price_cents: int


def make_item(name: str, price_cents: int) -> Item:
    """Builds a validated item: the name must not be blank and the price must be positive."""
    if not name.strip():
        raise ValueError("empty name")
    if price_cents <= 0:
        raise ValueError(f"invalid price for {name}")
    return Item(name=name, price_cents=price_cents)


def default_catalog() -> list[Item]:
    return [
        Item(name="Widget", price_cents=350),
        Item(name="Gadget", price_cents=1250),
        Item(name="Gizmo", price_cents=4999),
        Item(name="Cable", price_cents=725),
        Item(name="Case", price_cents=2400),
    ]


def find_item(items: list[Item], name: str) -> Item | None:
    return next((i for i in items if i.name == name), None)


def sorted_by_price(items: list[Item]) -> list[Item]:
    """Cheapest first."""
    return sorted(items, key=lambda i: i.price_cents)


def cheapest(items: list[Item]) -> Item | None:
    return min(items, key=lambda i: i.price_cents, default=None)


def catalog_text(items: list[Item]) -> str:
    """One line per item: "Widget - $3.50"."""
    return "\n".join(f"{i.name} - {format_amount(i.price_cents)}" for i in items)
