import math


def round2(x: float) -> float:
    """Rounds a dollar amount to the nearest cent, halves up."""
    return math.floor(x * 100.0 + 0.5) / 100.0


def format_amount(amount: float) -> str:
    """Formats a dollar amount: 12.5 -> "$12.50", -2.5 -> "-$2.50"."""
    sign = "-" if amount < 0.0 else ""
    return f"{sign}${abs(amount):.2f}"


def _is_digits(s: str) -> bool:
    return s.isascii() and s.isdigit()


def parse_amount(text: str) -> float:
    """Parses "12.5", "12" or "$12.50" (surrounding spaces allowed) into dollars."""
    t = text.strip()
    if t.startswith("$"):
        t = t[1:]
    parts = t.split(".")
    if len(parts) > 2 or not all(_is_digits(p) for p in parts):
        raise ValueError("invalid amount: " + text)
    return float(t)
