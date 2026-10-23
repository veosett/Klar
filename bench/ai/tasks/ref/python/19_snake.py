def camel_to_snake(s: str) -> str:
    out = []
    for i, c in enumerate(s):
        if "A" <= c <= "Z":
            out.append(("_" if i > 0 else "") + c.lower())
        else:
            out.append(c)
    return "".join(out)
