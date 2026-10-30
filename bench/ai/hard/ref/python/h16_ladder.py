from collections import deque


def ladder(start: str, goal: str, words: list[str]) -> int:
    if start == goal:
        return 1
    if goal not in words:
        return 0
    left = set(words)
    queue = deque([(start, 1)])
    while queue:
        w, d = queue.popleft()
        for x in sorted(left):
            if len(x) == len(w) and sum(a != b for a, b in zip(x, w)) == 1:
                if x == goal:
                    return d + 1
                left.discard(x)
                queue.append((x, d + 1))
    return 0
