def tokens(src: str) -> list[str]:
    out: list[str] = []
    i = 0
    n = len(src)

    def letter(c: str) -> bool:
        return c.isascii() and (c.isalpha() or c == "_")

    def digit(c: str) -> bool:
        return c.isascii() and c.isdigit()

    while i < n:
        c = src[i]
        if c in " \t\n":
            i += 1
        elif letter(c):
            j = i
            while j < n and (letter(src[j]) or digit(src[j])):
                j += 1
            out.append(src[i:j])
            i = j
        elif digit(c):
            j = i
            while j < n and digit(src[j]):
                j += 1
            out.append(src[i:j])
            i = j
        elif c == '"':
            j = i + 1
            while j < n and src[j] != '"':
                j += 2 if src[j] == "\\" else 1
            if j >= n:
                raise ValueError("unterminated string")
            out.append(src[i:j + 1])
            i = j + 1
        elif src[i:i + 2] in ("==", "!=", "<=", ">=", "->"):
            out.append(src[i:i + 2])
            i += 2
        elif c in "+-*/<>=(){},;":
            out.append(c)
            i += 1
        else:
            raise ValueError("unexpected " + c)
    return out
