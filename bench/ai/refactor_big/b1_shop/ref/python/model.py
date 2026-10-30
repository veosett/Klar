from dataclasses import dataclass
from enum import Enum


class Status(Enum):
    """Where an order is in its life."""
    DRAFT = "draft"
    PAID = "paid"
    ON_HOLD = "on_hold"
    PACKED = "packed"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class Tier(Enum):
    BASIC = "basic"
    SILVER = "silver"
    GOLD = "gold"


class Category(Enum):
    BOOK = "book"
    TOY = "toy"
    FOOD = "food"
    TOOL = "tool"
    GARDEN = "garden"


@dataclass(frozen=True)
class Product:
    sku: str
    name: str
    price: int
    weight: float
    category: Category
    stock: int
    supplier: int


@dataclass(frozen=True)
class Customer:
    id: int
    first_name: str
    last_name: str
    email: str
    tier: Tier
    city: str


@dataclass(frozen=True)
class Line:
    sku: str
    qty: int
    unit_price: int


@dataclass(frozen=True)
class Order:
    id: int
    customer: int
    lines: list[Line]
    status: Status
    shipping: int
    day: int
