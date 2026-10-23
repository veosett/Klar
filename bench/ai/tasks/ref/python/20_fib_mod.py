def fib_mod(n: int, m: int) -> int:
    a, b = 0, 1
    for _ in range(n):
        a, b = b, (a + b) % m
    return a % m
