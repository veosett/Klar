#include <iostream>

int final_price(int price, int discount_percent, int tax_percent) {
    return price * (100 - discount_percent) / 100 * (100 + tax_percent) / 100;
}

int main() {
    std::cout << final_price(200, 20, 10) << "\n"; // BUG: tax and discount swapped (should be discount 10, tax 20)
}
