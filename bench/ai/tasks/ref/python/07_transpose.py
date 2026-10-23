def transpose(m: list[list[int]]) -> list[list[int]]:
    if not m:
        return []
    return [[row[j] for row in m] for j in range(len(m[0]))]
