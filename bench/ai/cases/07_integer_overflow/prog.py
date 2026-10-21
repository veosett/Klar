def factorial(n: int) -> int:
    r = 1
    for i in range(2, n + 1):
        r = r * i  # BUG?: overflows in most languages
    return r


print(factorial(25))
