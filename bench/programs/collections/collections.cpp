#include <algorithm>
#include <chrono>
#include <cstdio>
#include <numeric>
#include <vector>
int main() {
    auto t0 = std::chrono::steady_clock::now();
    std::vector<long> xs(200000);
    std::iota(xs.begin(), xs.end(), 0L);
    std::vector<long> mapped;
    mapped.reserve(xs.size());
    std::transform(xs.begin(), xs.end(), std::back_inserter(mapped), [](long x) { return (x * 7919) % 10007; });
    std::vector<long> ys;
    std::copy_if(mapped.begin(), mapped.end(), std::back_inserter(ys), [](long x) { return x % 2 == 0; });
    std::stable_sort(ys.begin(), ys.end());
    long total = std::accumulate(ys.begin(), ys.end(), 0L);
    long median = ys[ys.size() / 2];
    double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
    std::printf("result=%zu,%ld,%ld\ntime_ms=%.3f\n", ys.size(), total, median, ms);
}
