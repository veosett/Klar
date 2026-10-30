import re


def run_vars(lines: list[str]) -> dict[str, int]:
    env: dict[str, int] = {}
    for line in lines:
        w = line.split()
        if len(w) < 3 or len(w) % 2 == 0 or w[1] != "=" or not re.fullmatch(r"[a-z]+", w[0]):
            raise ValueError("syntax error")
        for k, t in enumerate(w[2:]):
            if k % 2 == 0 and not re.fullmatch(r"-?[0-9]+|[a-z]+", t):
                raise ValueError("syntax error")
            if k % 2 == 1 and t not in ("+", "-"):
                raise ValueError("syntax error")
        acc = 0
        op = "+"
        for k, t in enumerate(w[2:]):
            if k % 2 == 1:
                op = t
                continue
            if t[0] in "-0123456789":
                v = int(t)
            elif t in env:
                v = env[t]
            else:
                raise ValueError("undefined " + t)
            acc = acc + v if op == "+" else acc - v
        env[w[0]] = acc
    return env
