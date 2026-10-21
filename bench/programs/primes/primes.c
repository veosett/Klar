#include <stdio.h>
#include <time.h>
static int is_prime(long n) {
    if (n < 2) return 0;
    if (n % 2 == 0) return n == 2;
    for (long d = 3; d * d <= n; d += 2) if (n % d == 0) return 0;
    return 1;
}
int main(void) {
    struct timespec a, b; clock_gettime(CLOCK_MONOTONIC, &a);
    volatile long limit = 30000;
    long count = 0;
    for (long n = 0; n < limit; n++) count += is_prime(n);
    clock_gettime(CLOCK_MONOTONIC, &b);
    printf("result=%ld\ntime_ms=%.3f\n", count, (b.tv_sec - a.tv_sec) * 1e3 + (b.tv_nsec - a.tv_nsec) / 1e6);
    return 0;
}
