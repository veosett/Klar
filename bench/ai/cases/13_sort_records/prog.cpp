#include <algorithm>
#include <iostream>
#include <string>
#include <vector>

struct Person { std::string name; int age; };

int main() {
    std::vector<Person> people{{"cat", 3}, {"ann", 1}, {"bob", 2}};
    std::sort(people.begin(), people.end()); // BUG: Person has no order; meant sort by age
    for (size_t i = 0; i < people.size(); i++) std::cout << (i ? "," : "") << people[i].name;
    std::cout << "\n";
}
