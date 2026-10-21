use std::time::Instant;
fn fib(n: i64) -> i64 { if n < 2 { n } else { fib(n - 1) + fib(n - 2) } }
fn main() {
    let a = Instant::now();
    let r = fib(std::hint::black_box(25));
    let ms = a.elapsed().as_secs_f64() * 1000.0;
    println!("result={}\ntime_ms={:.3}", r, ms);
}
