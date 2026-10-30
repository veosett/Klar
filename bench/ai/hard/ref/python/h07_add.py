def add_decimal(a: str, b: str) -> str:
    out = []
    carry = 0
    i, j = len(a) - 1, len(b) - 1
    while i >= 0 or j >= 0 or carry:
        s = carry
        if i >= 0:
            s += ord(a[i]) - 48
            i -= 1
        if j >= 0:
            s += ord(b[j]) - 48
            j -= 1
        out.append(chr(48 + s % 10))
        carry = s // 10
    return "".join(reversed(out)).lstrip("0") or "0"
