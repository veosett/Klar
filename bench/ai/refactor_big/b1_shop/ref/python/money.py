import math


def plain(cents: int) -> str:
    """Money as digits: "12.50"."""
    a = abs(cents)
    sign = "-" if cents < 0 else ""
    return f"{sign}{a // 100}.{a % 100:02d}"


def fmt(cents: int) -> str:
    """Money as text: "$12.50"."""
    return "$" + plain(cents)


def pct(cents: int, rate: float) -> int:
    """A share of an amount, rounded half up to the cent."""
    return math.floor(cents * rate + 0.5)


def avg(total: int, n: int) -> int:
    """The average of `n` amounts, rounded half up."""
    if n <= 0:
        return 0
    return (2 * total + n) // (2 * n)
