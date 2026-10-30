from model import Category, Customer, Line, Order, Product, Status, Tier


def sample_products() -> list[Product]:
    """Products for the demo and for trying things out."""
    return [
        Product("B1", "Atlas", 24.5, 1.2, Category.BOOK, 4, 1),
        Product("T1", "Kite", 12.0, 0.4, Category.TOY, 9, 2),
        Product("F1", "Tea", 6.75, 0.2, Category.FOOD, 30, 3),
        Product("H1", "Spade", 135.0, 2.5, Category.GARDEN, 2, 2),
    ]


def sample_customers() -> list[Customer]:
    """Customers for the demo."""
    return [
        Customer(1, "Ada Lovelace", "ada@example.org", Tier.GOLD, "Harbour"),
        Customer(2, "Alan Turing", "alan@example.org", Tier.BASIC, "Summit"),
    ]


def sample_orders() -> list[Order]:
    """Orders for the demo."""
    return [
        Order(100, 1, [Line("B1", 2, 24.5)], Status.PAID, 4.99, 1),
        Order(101, 2, [Line("H1", 1, 135.0), Line("F1", 4, 6.75)], Status.SHIPPED, 0.0, 2),
    ]
