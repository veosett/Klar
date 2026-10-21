#include <chrono>
#include <cstdio>
static long fib(long n) { return n < 2 ? n : fib(n - 1) + fib(n - 2); }
int main() {
    auto t0 = std::chrono::steady_clock::now();
    volatile long arg = 25;
    long r = fib(arg);
    double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
    std::printf("result=%ld\ntime_ms=%.3f\n", r, ms);
}
