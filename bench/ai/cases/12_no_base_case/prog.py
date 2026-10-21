def fact(n: int) -> int:
    return n * fact(n - 1)  # BUG: no base case


print(fact(5))
