def parse_csv_line(line: str) -> list[str]:
    fields, cur, i, quoted = [], "", 0, False
    while i < len(line):
        c = line[i]
        if quoted:
            if c == '"':
                if i + 1 < len(line) and line[i + 1] == '"':
                    cur += '"'
                    i += 1
                else:
                    quoted = False
            else:
                cur += c
        elif c == '"':
            quoted = True
        elif c == ",":
            fields.append(cur)
            cur = ""
        else:
            cur += c
        i += 1
    if quoted:
        raise ValueError("unterminated quote")
    fields.append(cur)
    return fields
