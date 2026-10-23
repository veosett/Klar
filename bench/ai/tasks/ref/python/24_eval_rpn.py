def eval_rpn(expr: str) -> int:
    stack: list[int] = []
    for tok in expr.split():
        if tok in ("+", "-", "*", "/"):
            if len(stack) < 2:
                raise ValueError("stack underflow")
            b, a = stack.pop(), stack.pop()
            if tok == "+":
                stack.append(a + b)
            elif tok == "-":
                stack.append(a - b)
            elif tok == "*":
                stack.append(a * b)
            else:
                if b == 0:
                    raise ValueError("division by zero")
                q = abs(a) // abs(b)
                stack.append(q if (a >= 0) == (b > 0) else -q)
        else:
            try:
                stack.append(int(tok))
            except ValueError:
                raise ValueError(f"bad token {tok}") from None
    if len(stack) != 1:
        raise ValueError("bad expression")
    return stack[0]
