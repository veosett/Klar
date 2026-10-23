def merge_intervals(xs: list[list[int]]) -> list[list[int]]:
    out: list[list[int]] = []
    for a, b in sorted(xs):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out
