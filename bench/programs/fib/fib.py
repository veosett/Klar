import time
def fib(n):
    if n < 2:
        return n
    return fib(n - 1) + fib(n - 2)

def main():
    start = time.perf_counter()
    r = fib(25)
    elapsed = (time.perf_counter() - start) * 1000
    print(f"result={r}")
    print(f"time_ms={elapsed:.3f}")

main()
