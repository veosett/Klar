#include <iostream>
#include <string>

std::string trim(const std::string& s) {
    size_t a = s.find_first_not_of(' '), b = s.find_last_not_of(' ');
    return a == std::string::npos ? "" : s.substr(a, b - a + 1);
}

int main() {
    std::string name = "  ann  ";
    trim(name); // BUG: the trimmed copy is thrown away
    std::cout << "[" << name << "]\n";
}
