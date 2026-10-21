#include <iostream>

int main() {
    int n = 7;
    std::cout << "total: " + n << "\n"; // BUG: Str + Int
}
