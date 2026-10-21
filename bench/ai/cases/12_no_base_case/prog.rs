fn fact(n: i64) -> i64 {
    n * fact(n - 1) // BUG: no base case
}

fn main() {
    println!("{}", fact(5));
}
