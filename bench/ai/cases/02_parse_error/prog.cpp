#include <iostream>
#include <string>

int double_quantity(const std::string& text) {
    int qty = std::stoi(text);
    return qty * 2; // BUG: the text may not be a number
}

int main() {
    std::cout << double_quantity("12a") << "\n";
}
