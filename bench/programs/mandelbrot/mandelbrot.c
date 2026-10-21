#include <stdio.h>
#include <time.h>
int main(void) {
    struct timespec a, b; clock_gettime(CLOCK_MONOTONIC, &a);
    volatile int h = 60, w = 120;
    long inside = 0;
    for (int y = 0; y < h; y++) for (int x = 0; x < w; x++) {
        double cr = x / 120.0 * 3.5 - 2.5, ci = y / 60.0 * 2.0 - 1.0, zr = 0.0, zi = 0.0; int k = 0;
        while (k < 50 && zr * zr + zi * zi <= 4.0) { double t = zr * zr - zi * zi + cr; zi = 2.0 * zr * zi + ci; zr = t; k++; }
        if (k == 50) inside++;
    }
    clock_gettime(CLOCK_MONOTONIC, &b);
    printf("result=%ld\ntime_ms=%.3f\n", inside, (b.tv_sec - a.tv_sec) * 1e3 + (b.tv_nsec - a.tv_nsec) / 1e6);
    return 0;
}
