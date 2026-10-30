def plain(amount: float) -> str:
    """Money as digits: "12.50"."""
    return f"{amount:.2f}"


def fmt(amount: float) -> str:
    """Money as text: "$12.50"."""
    return "$" + plain(amount)


def round2(amount: float) -> float:
    """An amount rounded to the cent."""
    return round(amount, 2)
