#include <cstdio>

enum class Kind { Circle, Square, Triangle };
struct Shape { Kind kind; double a, b; };

double area(const Shape& s) {
    switch (s.kind) { // BUG: Triangle is not handled
        case Kind::Circle: return 3.14159 * s.a * s.a;
        case Kind::Square: return s.a * s.a;
    }
}

int main() {
    std::printf("%.1f\n", area({Kind::Triangle, 4.0, 3.0}));
}
