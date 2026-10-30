def lru(capacity: int, ops: list[str]) -> list[str]:
    cache: dict[str, str] = {}
    out: list[str] = []
    for op in ops:
        w = op.split()
        if w[0] == "put":
            if w[1] in cache:
                del cache[w[1]]
            elif len(cache) >= capacity and cache:
                del cache[next(iter(cache))]
            if capacity > 0:
                cache[w[1]] = w[2]
        elif w[1] in cache:
            v = cache.pop(w[1])
            cache[w[1]] = v
            out.append(v)
        else:
            out.append("-")
    return out
