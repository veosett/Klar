use std::time::Instant;
fn main() {
    let a = Instant::now();
    let n: i64 = std::hint::black_box(300000);
    let mut total: i64 = 0;
    for i in 0..n { total = (total + i * i) % 1000007; }
    let ms = a.elapsed().as_secs_f64() * 1000.0;
    println!("result={}\ntime_ms={:.3}", total, ms);
}
