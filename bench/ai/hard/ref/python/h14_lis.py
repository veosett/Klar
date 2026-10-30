def lis(xs: list[int]) -> list[int]:
    n = len(xs)
    length = [1] * n
    for i in range(n - 1, -1, -1):
        for j in range(i + 1, n):
            if xs[j] > xs[i]:
                length[i] = max(length[i], length[j] + 1)
    out: list[int] = []
    need = max(length, default=0)
    pos = 0
    while need > 0:
        best = -1
        for j in range(pos, n):
            if length[j] >= need and (not out or xs[j] > out[-1]) and (best < 0 or xs[j] < xs[best]):
                best = j
        out.append(xs[best])
        pos = best + 1
        need -= 1
    return out
