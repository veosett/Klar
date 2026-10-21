import time
def is_prime(n):
    if n < 2:
        return False
    if n % 2 == 0:
        return n == 2
    d = 3
    while d * d <= n:
        if n % d == 0:
            return False
        d += 2
    return True

def main():
    start = time.perf_counter()
    count = 0
    for n in range(30000):
        if is_prime(n):
            count += 1
    elapsed = (time.perf_counter() - start) * 1000
    print(f"result={count}")
    print(f"time_ms={elapsed:.3f}")

main()
