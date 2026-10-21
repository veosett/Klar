use std::time::Instant;
fn main() {
    let a = Instant::now();
    let parts: Vec<String> = (0..100000).map(|i| format!("item{}", i)).collect();
    let joined = parts.join(",");
    let back: Vec<&str> = joined.split(',').collect();
    let sevens = back.iter().filter(|s| s.ends_with('7')).count();
    let ms = a.elapsed().as_secs_f64() * 1000.0;
    println!("result={},{}\ntime_ms={:.3}", sevens, joined.len(), ms);
}
