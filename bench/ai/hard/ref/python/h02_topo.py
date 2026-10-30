def topo(deps: dict[str, list[str]]) -> list[str]:
    nodes = set(deps)
    for ds in deps.values():
        nodes.update(ds)
    done: list[str] = []
    seen: set[str] = set()
    while len(done) < len(nodes):
        ready = [n for n in nodes - seen if all(d in seen for d in deps.get(n, []))]
        if not ready:
            raise ValueError("cycle")
        best = min(ready)
        done.append(best)
        seen.add(best)
    return done
