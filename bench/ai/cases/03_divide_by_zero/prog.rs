fn average(xs: &[i64]) -> i64 {
    xs.iter().sum::<i64>() / xs.len() as i64 // BUG: the list may be empty
}

fn main() {
    println!("{}", average(&[]));
}
