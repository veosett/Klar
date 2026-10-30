from dataclasses import dataclass
from enum import Enum


class Status(Enum):
    """Where an order is in its life."""
    DRAFT = "draft"
    PAID = "paid"
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
    price: float
    weight: float
    category: Category
    stock: int
    supplier: int


@dataclass(frozen=True)
class Customer:
    id: int
    name: str
    email: str
    tier: Tier
    city: str


@dataclass(frozen=True)
class Line:
    sku: str
    qty: int
    unit_price: float


@dataclass(frozen=True)
class Order:
    id: int
    customer: int
    lines: list[Line]
    status: Status
    shipping: float
    day: int
