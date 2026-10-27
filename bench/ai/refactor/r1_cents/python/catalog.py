from dataclasses import dataclass

from money import format_amount


@dataclass(frozen=True)
class Item:
    name: str
    price: float


def make_item(name: str, price: float) -> Item:
    """Builds a validated item: the name must not be blank and the price must be positive."""
    if not name.strip():
        raise ValueError("empty name")
    if price <= 0.0:
        raise ValueError(f"invalid price for {name}")
    return Item(name=name, price=price)


def default_catalog() -> list[Item]:
    return [
        Item(name="Widget", price=3.5),
        Item(name="Gadget", price=12.5),
        Item(name="Gizmo", price=49.99),
        Item(name="Cable", price=7.25),
        Item(name="Case", price=24.0),
    ]


def find_item(items: list[Item], name: str) -> Item | None:
    return next((i for i in items if i.name == name), None)


def sorted_by_price(items: list[Item]) -> list[Item]:
    """Cheapest first."""
    return sorted(items, key=lambda i: i.price)


def cheapest(items: list[Item]) -> Item | None:
    return min(items, key=lambda i: i.price, default=None)


def catalog_text(items: list[Item]) -> str:
    """One line per item: "Widget - $3.50"."""
    return "\n".join(f"{i.name} - {format_amount(i.price)}" for i in items)
