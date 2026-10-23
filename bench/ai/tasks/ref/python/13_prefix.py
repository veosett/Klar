def common_prefix(words: list[str]) -> str:
    if not words:
        return ""
    p = words[0]
    for w in words[1:]:
        while not w.startswith(p):
            p = p[:-1]
    return p
