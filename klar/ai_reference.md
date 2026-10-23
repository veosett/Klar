# Klar 1.0 — compact reference for AI authors

Klar is a small, strict, statically typed language compiled to native code. Follow these rules
exactly; the compiler rejects everything else with a coded error (`klar explain CODE`).

## Workflow
0. With an MCP client, use the `klar mcp` server: tools `klar_dev`, `klar_check`, `klar_patch`, `klar_eval`, `klar_doc`, ….
1. Write code (with `test` blocks / doc-tests next to it).
2. `klar dev file.klar --json` — ONE step: check + all tests + run `main`; compact JSON with a `next` field.
   Or separately: `klar check --json`, `klar test --json`, `klar run`.
3. `klar fix file.klar` applies every safe machine fix (`;`, `&&`, missing named args, effects, ...);
   `klar fmt file.klar` normalizes the layout.
   Look things up instead of guessing: `klar doc split` / `klar doc List.sort` (signature + tested examples),
   `klar eval '"a,b".split(",")'` (value : type), `klar outline file.klar` (API of a file),
   `klar refs file.klar name`, `klar rename file.klar old new`, `klar coverage file.klar` (untested statements).
   Edit by name, not by rewriting files: `klar patch file.klar '{"edits": [{"replace": "fname", "with": "fn ..."}]}' --test --json`
   (also `Type.method`, `test:name`, `insert`+`after`/`before`, `delete`, `find`+`replace`+`in`, `rename`+`to`,
   `id` from `klar ast`); it writes only if there are no new errors and the tests pass.
   Packages: `klar add name --git URL --tag v1` (or `--path ../dir`) edits klar.toml and fetches; `klar fetch` after a
   clone; `klar deps --json` shows the tree.
4. Failures show values, both sides of `assert`, the Klar call stack, minimal property counterexamples.
5. `klar run` compiles to a native executable (cached); `klar build file.klar` writes a standalone
   `.exe`/ELF (`--target windows|linux|linux-arm64`, experimental `macos`); `klar profile file.klar` shows where time goes.

## Lexical
- One statement per line. NO semicolons. Blocks use `{ }`. Comments: `// ...`, doc comments: `/// ...`.
- Inside `( )` and `[ ]` newlines are ignored. A line starting with `.` continues a method chain.
  To break a long expression elsewhere, end the line with the operator (`a +` newline `b`), or wrap it in `( )`.
- Logic: `and`, `or`, `not` (never `&&`, `||`, `!`). No `++`, `+=`.
- Strings: double quotes, interpolation `"sum = {a + b}"`, literal brace `\{`. No string literals inside `{...}`.
- Names: types/variants `PascalCase`; functions/variables `snake_case`; `_x` silences unused warnings.

## Declarations (top level only)
```klar
type Point { x: Int, y: Int }                       // record (all fields required)
enum Shape { Circle(radius: Float), Square(side: Float), Empty }   // variant fields are named
fn area(s: Shape) -> Float { ... }                  // param types + return type required
fn first[T](xs: List[T]) -> Option[T] { ... }       // generics in [ ]
fn save(p: Point) -> Result[Unit, Str] uses io { ... }   // effects: io time rand fs net proc
fn div(a: Int, b: Int) -> Int
  requires b != 0                                   // precondition (pure Bool)
  ensures result * b <= a                           // postcondition; `result` = return value
{ return a / b }
test "div works" { assert div(7, 2) == 3 }          // tests sit next to code
```
```klar
use geometry.{Point, area}                          // first lines of a file; loads geometry.klar next to it
pub fn area(p: Point) -> Float { ... }              // only `pub` fn/type/enum/const/trait can be imported (E0606)
use std.math.{gcd, mean}                            // standard modules: std.math std.text std.list std.result std.set std.json std.time
use geometry.shapes.{Circle}                        // a dependency from klar.toml: <geometry>/shapes.klar (`use geometry.{x}`: lib.klar)
type Pair2[A, B] { left: A, right: B }              // generic record (prelude already has Pair/Entry/Indexed)
enum Tree[T] { Leaf, Node(left: Tree[T], value: T, right: Tree[T]) }   // generic, recursive enum
type UserId = Int                                   // alias (transparent)
type Meters = new Float                             // newtype: a distinct type; build `Meters(2.5)`, read `m.value`
type Percent = new Int                              // its `requires` lines are the invariant, checked by `Percent(x)`
  requires value >= 0 and value <= 100              // (no `Percent { value: 5 }` / `with` on newtypes: E0217)
const MAX_USERS: Int = 100                          // constant: UPPER_SNAKE_CASE, typed, pure
/// Doc comment. Lines starting with >>> are doc-tests run by `klar test`:
/// >>> assert double(2) == 4
fn double(x: Int) -> Int { return x * 2 }
property "reverse twice" (xs: List[Int]) {          // runs 100 random inputs, shrinks failures
  assert xs.reverse().reverse() == xs
}
```
No top-level variables (use `const`). No nested named functions (use lambdas). Imports are explicit (no `*`);
type names are unique across the program.
Entry point: `fn main() uses io { ... }` or `fn main() -> Result[Unit, E] uses io`.

## Statements
```klar
let x = 5                 // immutable; shadowing ANY existing name is an error
var n: Int = 0            // reassignable
n = n + 1
let _ = may_fail()        // explicitly discard a value
if a > b { ... } else if a == b { ... } else { ... }      // statement, not expression
while cond { ... }        // break / continue allowed
for item in list { ... }  // only List; use range(0, n), m.keys(), s.chars()
return value              // REQUIRED: no implicit return of the last expression
assert x > 0, "message"
```

## Expressions
- Literals: `1`, `1_000`, `2.5`, `true`, `"s"`, `()` (Unit), `[1, 2]`, `Map { "a": 1 }`, `Map {}`.
- Arithmetic `+ - * / %` only on same types: Int with Int, Float with Float (`/` on Int truncates). `+` joins Str.
- IEEE-754 bits of a Float: `x.to_bits()` (signed 64-bit Int), back with `float_from_bits(n)`.
  No implicit conversions: `n.to_float()`, `f.round()`, `x.to_str()`.
- No bit operators: `a.bit_and(b)`, `bit_or`, `bit_xor`, `a.bit_not()`, `a.shift_left(n)`, `a.shift_right(n)`
  (two's complement on arbitrary-precision Int, shift_right floors). Characters: `s.codes()` → `List[Int]`,
  `n.to_char()` → `Option[Str]`.
- Bytes: `bytes_of([1, 2])`, `s.to_bytes()`, `b.push(255)`, `b.push_le(value, 4)` (little-endian, size 1/2/4/8),
  `b.get(i)`, `b.slice(a, z)`, `b.decode()` → `Result[Str, Str]`, `b.hex()`; files: `read_bytes`/`write_bytes` (fs).
- Comparison `== != < > <= >=` (no chaining). `==` is structural; values that contain functions cannot be compared (E0211).
- Records: `Point { x: 1, y: 2 }`, field `p.x`, copy-with-changes `p with { x: 3 }`. Fields are never assigned.
- Enum values: `Shape.Circle(radius: 1.0)`, `Shape.Empty` — always qualified.
- Option: `Some(v)`, `None`. Result: `Ok(v)`, `Err(e)`. No null, no exceptions.
- `expr?` unwraps Some/Ok, otherwise returns None/Err from the current function (same error type).
- Lambdas: `fn(x) => x * 2`, `fn(x: Int) -> Int { return x * 2 }` (no `=>` before a block). Param types may be
  inferred. Lambdas may capture `let` values but not a `var` (E0216): snapshot it (`let n_now = n`) or use `fold`.
- Calls: `f(a, b)`; functions with 3+ parameters REQUIRE named args: `f(a: 1, b: 2, c: 3)`.
- Method syntax works for any function on its first parameter: `acc.deposit(10)` == `deposit(acc, 10)`.
- `match` is an expression and must be exhaustive:
```klar
let label = match shape {
  Shape.Circle(r) => "circle {r}",
  Shape.Square(_) => "square",
  Shape.Empty => "empty",
}
match result {
  Ok(v) => print(v),
  Err(e) => { return Err(e) },      // block arm; type Unit unless it returns
}
let sign = match n > 0 { true => 1, false => -1 }      // instead of ternary / if-expression
```
Patterns: `_`, `name`, literals (`1`, `"a"`, `true`), `Some(p)`, `None`, `Ok(p)`, `Err(p)`, `Enum.Variant(p1, p2)`.
Guards: `x if x > 0 => ...` (guarded arms never count for exhaustiveness).
Negative literal receivers need parentheses: `(-5).abs()`.

## Immutability (most common mistake)
All values are immutable. Methods return NEW values:
```klar
var xs: List[Int] = []
xs = xs.push(1)            // correct
xs.push(1)                 // ERROR E0405: result discarded, xs unchanged
var m: Map[Str, Int] = Map {}
m = m.set("k", 1)
```
No indexing `xs[i]`: use `xs.get(i)` → `Option[T]`. No `unwrap`: use `?`, `match`, `.unwrap_or(d)`.

## Traits (shared methods of different types)
```klar
trait Shape {
  fn area(self) -> Float                 // required: every impl defines it
  fn label(self) -> Str {                // default: an impl may override it
    return "area {self.area()}"
  }
}
impl Shape for Circle {                  // for Int/Float/Bool/Str/Bytes or your own type/enum
  fn area(self) -> Float {
    return 3.14 * self.r * self.r
  }
}
fn total[T: Shape](xs: List[T]) -> Float {     // bound; several: [T: Shape + Show]
  return xs.map(fn(s) => s.area()).sum_float()
}
```
Methods take `self` first; `Self` is the implementing type. Call them with a dot: `c.area()` (never `area(c)`).
An impl lives in the trait's or the type's module; import the trait to use its methods. A trait is not a type:
for a list of different kinds use an `enum` and `impl Shape for ThatEnum` (one `match` per method).
Generic types get generic impls that cover every instance: `impl[T: Show] Show for List[T]`, `impl[T] Show for Box[T]`,
`impl[K, V] Show for Map[K, V]` (the target's arguments are exactly the impl's parameters; no `impl Show for List[Int]`).
`klar fix` adds `todo(...)` stubs for missing impl methods.

## Types
`Int` (arbitrary precision), `Float`, `Bool`, `Str`, `Bytes`, `Unit`, `Never`, `List[T]`, `Map[K, V]` (K: any value without
functions, insertion-ordered), `Option[T]`, `Result[T, E]`, `fn(A, B) -> R`, user `type`/`enum`. Annotate empty
collections: `let xs: List[Int] = []`.

## Effects
A function without `uses` is pure. Calling something with an effect requires declaring it:
`print`/`eprint` (stderr)/`read_line`/`read_exact(n)`/`cli_args`/`dbg` → `io`, `now_ms` (wall clock, ms since 1970 UTC)/`now_ns` (monotonic, for measuring) → `time`, `random_int` → `rand`,
`read_file`/`write_file`/`file_exists`/`list_dir` (sorted names)/`is_dir`/`make_dir`/`remove_file`/`current_dir` → `fs` (they return `Result`, never crash), `env_var(name)` → `Option[Str]` and
`exit(code)` (type `Never`, flushes output) → `io`; `run_command(["prog", "arg"])` → `Result[Int, Str]` (exit code;
inherits stdin/stdout/stderr, searches `PATH`) → `proc`; `run_capture(args, dir, input)` → `Result[List[Str], Str]`
(`[exit code, stdout, stderr]`) → `proc`; `set_executable(path)` → `fs`. Contracts and constants must be
pure. Tests may use only `io`.
Lambdas inherit the effects of the enclosing function.
Parallel: `xs.par_map(f)` = `xs.map(f)` computed on all CPU cores. `f` must be a lambda without effects or a
function name without `uses` (E0401/E0406; not a variable of fn type); results must not contain functions. Do the
effects (print, files) afterwards with the returned list.

## Debugging helpers
`dbg(expr)` prints `[dbg file:line] expr = value` to stderr and returns the value. `todo("what")` has type `Never`:
it type-checks anywhere, warns (W0404) and fails at runtime (R0012) — use it to sketch code first.

## Compile-time safety (like Rust: rejected before the program runs)
- Int `a / b` and `a % b` compile only if `b` is provably non-zero (E0701): a non-zero literal/constant,
  `if b != 0 { ... }`, early `if b == 0 { return ... }`, `match b { 0 => ..., _ => a / b }`, `requires b != 0`,
  `assert b != 0`, `if xs.is_empty() { return ... }` before dividing by `xs.len()`, `ensures result > 0` on the
  function that produced `b`, or a `var` that starts positive and only grows (`var d = 3 ... d = d + 2`).
- A function that calls itself on every path is an error (E0702) — write the base case first.
- Calls with constant arguments are checked against `requires` (E0703) and built-in domains (E0704); simple contracts
  (`n > 0`, `x != 0.0`, `not xs.is_empty()`) also against the signs the conditions prove (`if n <= 0 { f(n) }` → E0703),
  and `return`s against simple `ensures` (`ensures result >= 0` + `return -1` → E0706).
- `sort`/`min`/`max` need Int/Float/Str elements (E0215); for records use `sort_by(fn(p) => p.field)`.
- No null, no exceptions, no indexing, no overflow, no shared mutation — those failures cannot be written.

## Ignored values
A discarded `Result` is an error (E0402). Other discarded non-Unit values warn (W0401). Use `let _ = ...`.
