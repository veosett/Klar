#include <chrono>
#include <cstdio>
#include <string>
#include <vector>
int main() {
    auto t0 = std::chrono::steady_clock::now();
    std::vector<std::string> parts;
    parts.reserve(100000);
    for (int i = 0; i < 100000; i++) parts.push_back("item" + std::to_string(i));
    std::string joined;
    for (size_t i = 0; i < parts.size(); i++) { if (i) joined += ','; joined += parts[i]; }
    std::vector<std::string> back;
    size_t start = 0;
    for (;;) {
        size_t p = joined.find(',', start);
        if (p == std::string::npos) { back.push_back(joined.substr(start)); break; }
        back.push_back(joined.substr(start, p - start));
        start = p + 1;
    }
    long sevens = 0;
    for (const auto &s : back) if (!s.empty() && s.back() == '7') sevens++;
    double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
    std::printf("result=%ld,%zu\ntime_ms=%.3f\n", sevens, joined.size(), ms);
}
