#include <iostream>
#include <string>
#include <vector>

int main() {
    std::vector<std::string> names{"ann", "bob", "cat"};
    std::cout << names.length() << "\n"; // BUG: name from another language
}
