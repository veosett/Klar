import time

def main():
    start = time.perf_counter()
    parts = [f"item{i}" for i in range(100000)]
    joined = ",".join(parts)
    back = joined.split(",")
    sevens = len([s for s in back if s.endswith("7")])
    elapsed = (time.perf_counter() - start) * 1000
    print(f"result={sevens},{len(joined)}")
    print(f"time_ms={elapsed:.3f}")

main()
