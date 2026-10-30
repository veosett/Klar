def medians(xs: list[int], k: int) -> list[float]:
    if k < 1 or k > len(xs):
        return []
    out: list[float] = []
    for s in range(len(xs) - k + 1):
        w = sorted(xs[s:s + k])
        out.append(float(w[k // 2]) if k % 2 else (w[k // 2 - 1] + w[k // 2]) / 2)
    return out
