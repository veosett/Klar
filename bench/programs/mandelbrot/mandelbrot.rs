use std::time::Instant;
fn main() {
    let a = Instant::now();
    let (h, w) = std::hint::black_box((60, 120));
    let mut inside = 0;
    for y in 0..h { for x in 0..w {
        let cr = x as f64 / 120.0 * 3.5 - 2.5; let ci = y as f64 / 60.0 * 2.0 - 1.0;
        let (mut zr, mut zi, mut k) = (0.0f64, 0.0f64, 0);
        while k < 50 && zr * zr + zi * zi <= 4.0 { let t = zr * zr - zi * zi + cr; zi = 2.0 * zr * zi + ci; zr = t; k += 1; }
        if k == 50 { inside += 1; }
    } }
    let ms = a.elapsed().as_secs_f64() * 1000.0;
    println!("result={}\ntime_ms={:.3}", inside, ms);
}
