def spiral(m: list[list[int]]) -> list[int]:
    out: list[int] = []
    rows = [list(r) for r in m]
    while rows and rows[0]:
        out += rows.pop(0)
        rows = [list(r) for r in zip(*rows)][::-1]
    return out
