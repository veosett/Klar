def final_price(price: int, discount_percent: int, tax_percent: int) -> int:
    return price * (100 - discount_percent) // 100 * (100 + tax_percent) // 100


print(final_price(200, 20, 10))  # BUG: tax and discount swapped (should be discount 10, tax 20)
