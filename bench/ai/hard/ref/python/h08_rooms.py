def rooms(meetings: list[list[int]]) -> int:
    events = sorted([(s, 1) for s, _ in meetings] + [(e, -1) for _, e in meetings], key=lambda x: (x[0], x[1]))
    best = cur = 0
    for _, d in events:
        cur += d
        best = max(best, cur)
    return best
