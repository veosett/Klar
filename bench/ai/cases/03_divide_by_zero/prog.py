def average(xs: list[int]) -> int:
    return sum(xs) // len(xs)  # BUG: the list may be empty


print(average([]))
