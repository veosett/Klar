def average(xs: list[int]) -> float | None:
    if not xs:
        return None
    return sum(xs) / len(xs)
