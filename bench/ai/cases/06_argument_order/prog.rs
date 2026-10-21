fn final_price(price: i64, discount_percent: i64, tax_percent: i64) -> i64 {
    price * (100 - discount_percent) / 100 * (100 + tax_percent) / 100
}

fn main() {
    println!("{}", final_price(200, 20, 10)); // BUG: tax and discount swapped (should be discount 10, tax 20)
}
