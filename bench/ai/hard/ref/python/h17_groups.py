def groups(pairs: list[list[str]]) -> list[list[str]]:
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            x = parent[x]
        return x

    for a, b in pairs:
        parent[find(a)] = find(b)
    out: dict[str, list[str]] = {}
    for x in parent:
        out.setdefault(find(x), []).append(x)
    return sorted(sorted(g) for g in out.values())
