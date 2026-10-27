def round_div(n: int, d: int) -> int:
    """n / d rounded to the nearest integer, halves up (n >= 0, d > 0)."""
    return (2 * n + d) // (2 * d)


def format_amount(cents: int) -> str:
    """Formats an amount in cents: 1250 -> "$12.50", -250 -> "-$2.50"."""
    sign = "-" if cents < 0 else ""
    abs_cents = abs(cents)
    return f"{sign}${abs_cents // 100}.{abs_cents % 100:02d}"


def _is_digits(s: str) -> bool:
    return s.isascii() and s.isdigit()


def parse_amount(text: str) -> int:
    """Parses "12.5", "12" or "$12.50" (surrounding spaces allowed, at most 2 decimals) into cents."""
    t = text.strip()
    if t.startswith("$"):
        t = t[1:]
    parts = t.split(".")
    if len(parts) > 2 or not all(_is_digits(p) for p in parts):
        raise ValueError("invalid amount: " + text)
    frac = parts[1] if len(parts) == 2 else ""
    if len(frac) > 2:
        raise ValueError("invalid amount: " + text)
    return int(parts[0]) * 100 + int(frac.ljust(2, "0"))
