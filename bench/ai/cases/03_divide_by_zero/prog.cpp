#include <iostream>
#include <numeric>
#include <vector>

int average(const std::vector<int>& xs) {
    return std::accumulate(xs.begin(), xs.end(), 0) / static_cast<int>(xs.size()); // BUG: the list may be empty
}

int main() {
    std::cout << average({}) << "\n";
}
