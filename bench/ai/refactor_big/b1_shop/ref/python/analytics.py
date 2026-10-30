from model import Customer, Order
from money import avg
from orders import grand_total, is_revenue


def revenue(os: list[Order]) -> int:
    """The money received over the given orders."""
    return sum(grand_total(o) for o in os if is_revenue(o.status))


def average_order(os: list[Order]) -> int:
    """The average value of the orders that brought money."""
    counted = [o for o in os if is_revenue(o.status)]
    return avg(revenue(counted), len(counted))


def full_name(id: int, cs: list[Customer]) -> str:
    for c in cs:
        if c.id == id:
            return f"{c.first_name} {c.last_name}"
    return "unknown"


def spend_by_customer(os: list[Order], cs: list[Customer]) -> dict[str, int]:
    """The money per customer's name."""
    m: dict[str, int] = {}
    for o in os:
        if is_revenue(o.status):
            who = full_name(o.customer, cs)
            m[who] = m.get(who, 0) + grand_total(o)
    return m


def top_customers(os: list[Order], cs: list[Customer], n: int) -> list[str]:
    """The customers who spent the most, by name."""
    ranked = sorted(spend_by_customer(os, cs).items(), key=lambda e: -e[1])
    return [e[0] for e in ranked[:n]]


def revenue_by_city(os: list[Order], cs: list[Customer]) -> dict[str, int]:
    """The money per city."""
    cities = {c.id: c.city for c in cs}
    m: dict[str, int] = {}
    for o in os:
        if is_revenue(o.status):
            city = cities.get(o.customer, "unknown")
            m[city] = m.get(city, 0) + grand_total(o)
    return m


def orders_over(os: list[Order], limit: int) -> list[Order]:
    """Orders worth at least this much."""
    return [o for o in os if grand_total(o) >= limit]


def big_orders(os: list[Order]) -> int:
    """The number of orders worth at least 1000.00."""
    return len(orders_over(os, 100000))


def daily_revenue(os: list[Order], day: int) -> int:
    """The orders of a day that brought money."""
    return revenue([o for o in os if o.day == day])
