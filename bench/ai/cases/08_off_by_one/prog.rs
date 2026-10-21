fn main() {
    let xs = vec![10, 20, 30];
    println!("last={}", xs[xs.len()]); // BUG: off by one
}
