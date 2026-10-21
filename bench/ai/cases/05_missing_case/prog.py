from dataclasses import dataclass


@dataclass
class Circle:
    radius: float


@dataclass
class Square:
    side: float


@dataclass
class Triangle:
    base: float
    height: float


Shape = Circle | Square | Triangle


def area(s: Shape) -> float:
    if isinstance(s, Circle):
        return 3.14159 * s.radius * s.radius
    elif isinstance(s, Square):  # BUG: Triangle is not handled
        return s.side * s.side


print(area(Triangle(4.0, 3.0)))
