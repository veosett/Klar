## Recipes (the usual shapes; do not write helpers for these)
```klar
for i in range(0, xs.len()) { total = total + xs.get_or(i, 0) * i }   // index loop; get_or instead of match on get
xs.enumerate().map(fn(e) => e.index * e.value)                        // index and value without a loop
let cs = s.chars()                                                    // List[Str] of one-character strings
cs.get_or(i, "")   s.slice(0, 2)   s.split(" ")   "A".codes()         // "" past the end ends a scan
"7".to_int().unwrap_or(0)   "42".is_numeric()   7.to_str()            // digits and numbers
grid = grid.set(r, grid.get_or(r, []).set(c, 9))                      // change a cell of a nested list
let top = stack.last()                                                // stack: push, last, take(len - 1)
stack = stack.take(stack.len() - 1)
let head = queue.first()                                              // queue: push, first, drop(1)
queue = queue.drop(1)
counts = counts.update(w, 0, fn(n) => n + 1)                          // count; `update(k, [], fn(l) => l.push(x))` groups
let n = s.trim().to_int().ok_or("bad number: {s}")?                   // Option to Result, then return the error
words.sort_by(fn(w) => -w.len())                                      // descending: negate the key
let label = match n > 2 { true => "many", false => "few" }            // instead of a ternary
let q = p with { pos: p.pos + 1 }                                     // state in a record
let now = limit                                                       // a lambda cannot capture a `var`: snapshot it
```
