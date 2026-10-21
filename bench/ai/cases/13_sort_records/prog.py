from dataclasses import dataclass


@dataclass
class Person:
    name: str
    age: int


people = [Person("cat", 3), Person("ann", 1), Person("bob", 2)]
ordered = sorted(people)  # BUG: Person has no order; meant sort by age
print(",".join(p.name for p in ordered))
