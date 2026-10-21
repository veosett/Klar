import time

def main():
    start = time.perf_counter()
    total = 0
    i = 0
    while i < 300000:
        total = (total + i * i) % 1000007
        i += 1
    elapsed = (time.perf_counter() - start) * 1000
    print(f"result={total}")
    print(f"time_ms={elapsed:.3f}")

main()
