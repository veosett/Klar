#include <iostream>

long long factorial(int n) {
    long long r = 1;
    for (int i = 2; i <= n; i++) {
        r = r * i; // BUG?: overflows in most languages
    }
    return r;
}

int main() {
    std::cout << factorial(25) << "\n";
}
