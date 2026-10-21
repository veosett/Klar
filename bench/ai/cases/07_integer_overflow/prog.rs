fn factorial(n: i64) -> i64 {
    let mut r: i64 = 1;
    for i in 2..=n {
        r = r * i; // BUG?: overflows in most languages
    }
    r
}

fn main() {
    println!("{}", factorial(25));
}
