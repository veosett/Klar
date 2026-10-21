use std::time::Instant;
fn main() {
    let a = Instant::now();
    let n: i64 = std::hint::black_box(200000);
    let mut ys: Vec<i64> = (0..n).map(|x| (x * 7919) % 10007).filter(|x| x % 2 == 0).collect();
    ys.sort();
    let total: i64 = ys.iter().sum();
    let median = ys[ys.len() / 2];
    let ms = a.elapsed().as_secs_f64() * 1000.0;
    println!("result={},{},{}\ntime_ms={:.3}", ys.len(), total, median, ms);
}
