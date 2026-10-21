fn main() {
    let n = 42;
    let label = "small";
    if n > 10 {
        let label = "big"; // BUG: declares a new variable instead of assigning
    }
    println!("{}", label);
}
