#include <stdio.h>
#include <time.h>
static long fib(long n) { return n < 2 ? n : fib(n - 1) + fib(n - 2); }
int main(void) {
    struct timespec a, b; clock_gettime(CLOCK_MONOTONIC, &a);
    long r = fib(25);
    clock_gettime(CLOCK_MONOTONIC, &b);
    printf("result=%ld\ntime_ms=%.3f\n", r, (b.tv_sec - a.tv_sec) * 1e3 + (b.tv_nsec - a.tv_nsec) / 1e6);
    return 0;
}
