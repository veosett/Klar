use std::collections::HashMap;

fn next_year_age(ages: &HashMap<&str, i64>, name: &str) -> i64 {
    ages[name] + 1 // BUG: the key may be missing
}

fn main() {
    let ages = HashMap::from([("ann", 31), ("bob", 42)]);
    println!("{}", next_year_age(&ages, "cat"));
}
