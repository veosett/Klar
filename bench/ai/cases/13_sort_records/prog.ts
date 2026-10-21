interface Person { name: string; age: number }

const people: Person[] = [{ name: "cat", age: 3 }, { name: "ann", age: 1 }, { name: "bob", age: 2 }];
const sorted = [...people].sort(); // BUG: Person has no order; meant sort by age
console.log(sorted.map((p) => p.name).join(","));
