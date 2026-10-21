#include <iostream>

long fact(long n) {
    return n * fact(n - 1); // BUG: no base case
}

int main() {
    std::cout << fact(5) << "\n";
}
