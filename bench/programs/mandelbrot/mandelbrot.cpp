#include <chrono>
#include <cstdio>
int main() {
    auto t0 = std::chrono::steady_clock::now();
    volatile int h = 60, w = 120;
    long inside = 0;
    for (int y = 0; y < h; y++)
        for (int x = 0; x < w; x++) {
            double cr = x / 120.0 * 3.5 - 2.5, ci = y / 60.0 * 2.0 - 1.0, zr = 0.0, zi = 0.0;
            int k = 0;
            while (k < 50 && zr * zr + zi * zi <= 4.0) { double t = zr * zr - zi * zi + cr; zi = 2.0 * zr * zi + ci; zr = t; k++; }
            if (k == 50) inside++;
        }
    double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
    std::printf("result=%ld\ntime_ms=%.3f\n", inside, ms);
}
