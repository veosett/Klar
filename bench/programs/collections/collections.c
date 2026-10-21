#include <stdio.h>
#include <stdlib.h>
#include <time.h>
static int cmp(const void *a, const void *b) { long x = *(const long *)a, y = *(const long *)b; return (x > y) - (x < y); }
int main(void) {
    struct timespec a, b; clock_gettime(CLOCK_MONOTONIC, &a);
    int n = 200000; long *ys = malloc(sizeof(long) * n); int len = 0;
    for (long x = 0; x < n; x++) { long v = (x * 7919) % 10007; if (v % 2 == 0) ys[len++] = v; }
    qsort(ys, len, sizeof(long), cmp);
    long total = 0; for (int i = 0; i < len; i++) total += ys[i];
    long median = ys[len / 2];
    clock_gettime(CLOCK_MONOTONIC, &b);
    printf("result=%d,%ld,%ld\ntime_ms=%.3f\n", len, total, median, (b.tv_sec - a.tv_sec) * 1e3 + (b.tv_nsec - a.tv_nsec) / 1e6);
    return 0;
}
