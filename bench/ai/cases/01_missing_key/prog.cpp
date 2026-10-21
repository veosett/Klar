#include <iostream>
#include <map>
#include <string>

int next_year_age(std::map<std::string, int>& ages, const std::string& name) {
    return ages[name] + 1; // BUG: the key may be missing
}

int main() {
    std::map<std::string, int> ages{{"ann", 31}, {"bob", 42}};
    std::cout << next_year_age(ages, "cat") << "\n";
}
