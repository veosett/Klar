fn double_quantity(text: &str) -> i64 {
    let qty: i64 = text.parse().unwrap();
    qty * 2 // BUG: the text may not be a number
}

fn main() {
    println!("{}", double_quantity("12a"));
}
