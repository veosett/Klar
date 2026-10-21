#include <iostream>
#include <vector>

int main() {
    std::vector<int> xs{10, 20, 30};
    std::cout << "last=" << xs[xs.size()] << "\n"; // BUG: off by one
}
