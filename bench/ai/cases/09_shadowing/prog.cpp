#include <iostream>
#include <string>

int main() {
    int n = 42;
    std::string label = "small";
    if (n > 10) {
        std::string label = "big"; // BUG: declares a new variable instead of assigning
    }
    std::cout << label << "\n";
}
