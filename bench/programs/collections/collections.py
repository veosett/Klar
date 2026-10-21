import time

def main():
    start = time.perf_counter()
    ys = sorted(x for x in ((x * 7919) % 10007 for x in range(200000)) if x % 2 == 0)
    total = sum(ys)
    median = ys[len(ys) // 2]
    elapsed = (time.perf_counter() - start) * 1000
    print(f"result={len(ys)},{total},{median}")
    print(f"time_ms={elapsed:.3f}")

main()
