def wrap(text: str, width: int) -> list[str]:
    pieces = []
    for w in text.split():
        pieces += [w[i:i + width] for i in range(0, len(w), width)]
    lines: list[str] = []
    line = ""
    for p in pieces:
        if not line:
            line = p
        elif len(line) + 1 + len(p) <= width:
            line += " " + p
        else:
            lines.append(line)
            line = p
    if line:
        lines.append(line)
    return lines
