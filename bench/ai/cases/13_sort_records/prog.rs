struct Person {
    name: &'static str,
    age: i64,
}

fn main() {
    let mut people = vec![Person { name: "cat", age: 3 }, Person { name: "ann", age: 1 }, Person { name: "bob", age: 2 }];
    people.sort(); // BUG: Person has no order; meant sort by age
    let names: Vec<&str> = people.iter().map(|p| p.name).collect();
    println!("{} {}", names.join(","), people[0].age * 0);
}
