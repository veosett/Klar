import time

def main():
    start = time.perf_counter()
    inside = 0
    for y in range(60):
        for x in range(120):
            cr = x / 120.0 * 3.5 - 2.5
            ci = y / 60.0 * 2.0 - 1.0
            zr = zi = 0.0
            k = 0
            while k < 50 and zr * zr + zi * zi <= 4.0:
                t = zr * zr - zi * zi + cr
                zi = 2.0 * zr * zi + ci
                zr = t
                k += 1
            if k == 50:
                inside += 1
    elapsed = (time.perf_counter() - start) * 1000
    print(f"result={inside}")
    print(f"time_ms={elapsed:.3f}")

main()
