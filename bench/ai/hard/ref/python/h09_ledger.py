def amount(s: str) -> int:
    if not (s.isascii() and s.isdigit()) or int(s) == 0:
        raise ValueError("bad op")
    return int(s)


def ledger(ops: list[str]) -> dict[str, int]:
    acc: dict[str, int] = {}

    def known(name: str) -> None:
        if name not in acc:
            raise ValueError("unknown " + name)

    for op in ops:
        w = op.split()
        if w[:1] == ["open"] and len(w) == 2:
            if w[1] in acc:
                raise ValueError("exists " + w[1])
            acc[w[1]] = 0
        elif w[:1] == ["dep"] and len(w) == 3:
            n = amount(w[2])
            known(w[1])
            acc[w[1]] += n
        elif w[:1] == ["wd"] and len(w) == 3:
            n = amount(w[2])
            known(w[1])
            if acc[w[1]] < n:
                raise ValueError("insufficient " + w[1])
            acc[w[1]] -= n
        elif w[:1] == ["move"] and len(w) == 4:
            n = amount(w[3])
            known(w[1])
            known(w[2])
            if acc[w[1]] < n:
                raise ValueError("insufficient " + w[1])
            acc[w[1]] -= n
            acc[w[2]] += n
        else:
            raise ValueError("bad op")
    return acc
