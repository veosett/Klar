def calc(expr: str) -> int:
    tokens = []
    i = 0
    while i < len(expr):
        c = expr[i]
        if c == " ":
            i += 1
        elif c.isascii() and c.isdigit():
            j = i
            while j < len(expr) and expr[j].isascii() and expr[j].isdigit():
                j += 1
            tokens.append(expr[i:j])
            i = j
        elif c in "+-*/()":
            tokens.append(c)
            i += 1
        else:
            raise ValueError("syntax error")
    pos = 0

    def peek():
        return tokens[pos] if pos < len(tokens) else ""

    def sum_():
        nonlocal pos
        acc = product()
        while peek() in ("+", "-"):
            op = peek()
            pos += 1
            v = product()
            acc = acc + v if op == "+" else acc - v
        return acc

    def product():
        nonlocal pos
        acc = unary()
        while peek() in ("*", "/"):
            op = peek()
            pos += 1
            v = unary()
            if op == "*":
                acc *= v
            elif v == 0:
                raise ValueError("division by zero")
            else:
                q = abs(acc) // abs(v)
                acc = q if (acc < 0) == (v < 0) else -q
        return acc

    def unary():
        nonlocal pos
        if peek() == "-":
            pos += 1
            return -unary()
        return primary()

    def primary():
        nonlocal pos
        t = peek()
        if t == "(":
            pos += 1
            v = sum_()
            if peek() != ")":
                raise ValueError("syntax error")
            pos += 1
            return v
        if t == "" or not t[0].isdigit():
            raise ValueError("syntax error")
        pos += 1
        return int(t)

    v = sum_()
    if pos != len(tokens):
        raise ValueError("syntax error")
    return v
