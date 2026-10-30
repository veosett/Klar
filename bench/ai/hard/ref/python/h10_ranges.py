def ranges(xs: list[int]) -> str:
    parts: list[str] = []
    values = sorted(set(xs))
    i = 0
    while i < len(values):
        j = i
        while j + 1 < len(values) and values[j + 1] == values[j] + 1:
            j += 1
        if j - i >= 2:
            parts.append(f"{values[i]}-{values[j]}")
        else:
            parts += [str(v) for v in values[i:j + 1]]
        i = j + 1
    return ",".join(parts)
