def double_quantity(text: str) -> int:
    qty = int(text)
    return qty * 2  # BUG: the text may not be a number


print(double_quantity("12a"))
