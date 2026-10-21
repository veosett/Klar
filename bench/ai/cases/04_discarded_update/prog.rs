fn main() {
    let name = "  ann  ";
    name.trim(); // BUG: the trimmed copy is thrown away
    println!("[{}]", name);
}
