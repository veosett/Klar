use std::time::Instant;
fn is_prime(n: i64) -> bool {
    if n < 2 { return false; }
    if n % 2 == 0 { return n == 2; }
    let mut d = 3;
    while d * d <= n { if n % d == 0 { return false; } d += 2; }
    true
}
fn main() {
    let a = Instant::now();
    let limit: i64 = std::hint::black_box(30000);
    let count = (0..limit).filter(|&n| is_prime(n)).count();
    let ms = a.elapsed().as_secs_f64() * 1000.0;
    println!("result={}\ntime_ms={:.3}", count, ms);
}
