def divide_all(xs: list[int], ys: list[int]) -> list[int]:
    out = []
    for i, (x, y) in enumerate(zip(xs, ys)):
        if y == 0:
            raise ValueError(f"division by zero at index {i}")
        q = abs(x) // abs(y)
        out.append(q if (x >= 0) == (y > 0) else -q)
    return out
