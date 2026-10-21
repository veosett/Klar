#include <chrono>
#include <cstdio>
int main() {
    auto t0 = std::chrono::steady_clock::now();
    volatile long long n = 300000;
    long long total = 0;
    for (long long i = 0; i < n; i++) total = (total + i * i) % 1000007;
    double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
    std::printf("result=%lld\ntime_ms=%.3f\n", total, ms);
}
