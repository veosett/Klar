#include <stdio.h>
#include <time.h>
int main(void) {
    struct timespec a, b; clock_gettime(CLOCK_MONOTONIC, &a);
    volatile long long n = 300000;
    long long total = 0;
    for (long long i = 0; i < n; i++) total = (total + i * i) % 1000007;
    clock_gettime(CLOCK_MONOTONIC, &b);
    printf("result=%lld\ntime_ms=%.3f\n", total, (b.tv_sec - a.tv_sec) * 1e3 + (b.tv_nsec - a.tv_nsec) / 1e6);
    return 0;
}
