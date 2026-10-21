#include <chrono>
#include <cstdio>
static bool is_prime(long n) {
    if (n < 2) return false;
    if (n % 2 == 0) return n == 2;
    for (long d = 3; d * d <= n; d += 2) if (n % d == 0) return false;
    return true;
}
int main() {
    auto t0 = std::chrono::steady_clock::now();
    volatile long limit = 30000;
    long count = 0;
    for (long n = 0; n < limit; n++) count += is_prime(n);
    double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
    std::printf("result=%ld\ntime_ms=%.3f\n", count, ms);
}
