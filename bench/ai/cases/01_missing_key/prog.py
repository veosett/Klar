def next_year_age(ages: dict[str, int], name: str) -> int:
    return ages.get(name) + 1  # BUG: the key may be missing


ages = {"ann": 31, "bob": 42}
print(next_year_age(ages, "cat"))
