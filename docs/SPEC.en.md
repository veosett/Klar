# Klar 1.0 — language specification

This document describes the Klar language, version 1.0: lexical structure, grammar, types, semantics, tests, modules
and packages, and the execution model ([на русском](SPEC.md)). The compact version for prompts is `klar spec` (the
file `klar/ai_reference.md` plus the standard library signatures). The reference behaviour is the interpreter
`klar/interpreter.py` together with the type checker `klar/checker.py`; both compilers (`klar`, in Python, and
`klarc`, in Klar) must behave like the reference, and the tests check it (section 10).

## 0. Stability

Klar follows [Semantic Versioning](https://semver.org/). From 1.0 on, every 1.x version guarantees:

* **Source code.** A program that passes `klar check` in 1.0 passes it in every 1.x and does the same thing. There
  will be no new keywords in 1.x. The one exception is new built-in functions and methods, which may appear in minor
  versions (1.1, 1.2, …): if a program already uses such a name for its own function, the compiler says so
  (E0101/E0102; an `impl` method named like a new built-in method is E0221), and in method syntax a built-in method
  wins over a user function (section 4). Every new built-in name is therefore listed in the CHANGELOG.
* **Diagnostic codes.** A code (`E0205`, `R0002`, `W0401`, …) keeps its meaning; new checks get new codes. Message
  texts, hints and suggested fixes may change.
* **Warnings** may be added (a program with a new warning still compiles).
* **Standard library.** The signatures of built-in functions, methods and `std.*` modules are neither changed nor
  removed; new ones are only added.
* **`klar.toml` and `klar.lock`** — compatible extensions only.
* **Machine-readable output** of the tools (`--json`) — fields are neither removed nor given a new meaning; new ones
  may appear.

Not guaranteed: speed, the size and internals of executables, the text of `klar spec`, the internal interfaces of the
compilers (`klar/*.py`, `compiler/*.klar`, `klar/rt/*.klar`) and everything marked **experimental** (currently: the
`macos` target, section 9). Where the implementation disagrees with this specification, the implementation is fixed.

## 1. Lexical structure

| Element | Rule |
|---|---|
| Encoding | UTF-8 |
| Comments | `// to the end of the line`; `/// doc comment` before a top-level declaration |
| Identifiers | a letter or `_`, then letters, digits, `_` (letters need not be Latin, but non-ASCII names get warning W0104); types, traits and variants `PascalCase`, functions and variables `snake_case`, constants `UPPER_SNAKE_CASE`; `_x` marks a deliberately unused name |
| Keywords | `module use pub fn type enum trait impl const let var return if else while for in break continue match test property assert requires ensures uses and or not true false with` |
| Integers | `42`, `1_000_000` (arbitrary precision; digits `0`–`9` only, no suffixes) |
| Floats | `3.14`, `0.5` (a digit is required on both sides of the point) |
| Strings | `"..."`, escapes `\n \t \r \0 \\ \" \{ \}`, interpolation `{expr}` (no string literals inside `{...}`) |
| Operators | `+ - * / % == != < > <= >= = -> => ( ) [ ] { } , : . ?` |
| End of statement | a newline (ignored inside `()` and `[]`; a line starting with `.` continues the previous one; a line ending with a binary operator continues on the next) |

The lexer rejects tokens from other languages with a hint: `&& || ! ; ++ -- += -= *= :: ' | & ^ ~ << >> # @` and the
backtick (E0001).

## 2. Grammar (EBNF)

```ebnf
program     = [ "module" ident { "." ident } NL ] { use_decl NL } { [ doc ] [ "pub" ] decl NL } ;
                                                     (* pub: fn, type, enum, const, trait *)
use_decl    = "use" ident { "." ident } "." "{" ident { "," ident } "}" ;   (* explicit names only *)
doc         = { "///" text NL } ;                    (* lines "/// >>> stmt" are doc-tests *)
decl        = fn_decl | type_decl | alias_decl | newtype_decl | enum_decl | trait_decl | impl_decl | const_decl | test_decl
            | property_decl ;

fn_decl     = "fn" ident [ tparams ]
              "(" [ param { "," param } ] ")" [ "->" type ]
              [ "uses" ident { "," ident } ]
              { NL? ( "requires" expr | "ensures" expr ) }
              block ;
tparams     = "[" tparam { "," tparam } "]" ;
tparam      = Ident [ ":" Ident { "+" Ident } ] ;              (* bounds: functions and impls only *)
param       = ident ":" type ;
trait_decl  = "trait" Ident "{" { [ doc ] method_sig [ block ] NL } "}" ;   (* a body = a default method *)
impl_decl   = "impl" [ tparams ] Ident "for" type "{" { [ doc ] method_sig block NL } "}" ;
method_sig  = "fn" ident "(" "self" { "," param } ")" [ "->" type ] [ "uses" ident { "," ident } ]
              { NL? ( "requires" expr | "ensures" expr ) } ;    (* signatures may use the type Self *)
type_decl   = "type" Ident [ tparams ] "{" { ident ":" type [","] } "}" ;
alias_decl  = "type" Ident [ tparams ] "=" type ;
newtype_decl = "type" Ident [ tparams ] "=" "new" type { NL "requires" expr } ;   (* `new` is not a keyword here *)
enum_decl   = "enum" Ident [ tparams ] "{" { Ident [ "(" ident ":" type { "," ident ":" type } ")" ] [","] } "}" ;
const_decl  = "const" UPPER_IDENT ":" type "=" expr ;                    (* a pure expression *)
test_decl   = "test" string block ;
property_decl = "property" string "(" param { "," param } ")" block ;

type        = Ident [ "[" type { "," type } "]" ]
            | "fn" "(" [ type { "," type } ] ")" "->" type ;

block       = "{" { stmt NL } "}" ;
stmt        = ("let" | "var") ident [ ":" type ] "=" expr
            | ident "=" expr
            | "return" [ expr ]
            | if_stmt
            | "while" expr block
            | "for" ident "in" expr block
            | "break" | "continue"
            | "assert" expr [ "," expr ]
            | expr ;
if_stmt     = "if" expr block [ "else" ( if_stmt | block ) ] ;

expr        = or ;
or          = and { "or" and } ;
and         = not { "and" not } ;
not         = "not" not | cmp ;
cmp         = add [ ("=="|"!="|"<"|">"|"<="|">=") add ] ;      (* no chains *)
add         = mul { ("+"|"-") mul } ;
mul         = unary { ("*"|"/"|"%") unary } ;
unary       = "-" unary | postfix ;
postfix     = primary { "(" args ")" | "." ident [ "(" args ")" ] | "?" | "with" field_inits } ;
args        = [ arg { "," arg } [","] ] ;
arg         = [ ident ":" ] expr ;
primary     = int | float | string | "true" | "false" | "(" ")" | "(" expr ")"
            | "[" [ expr { "," expr } [","] ] "]"
            | "Map" "{" { expr ":" expr [","] } "}"
            | Ident field_inits                     (* record literal *)
            | ident
            | match
            | "fn" "(" [ ident [":" type] { "," ident [":" type] } ] ")" [ "->" type ] ( "=>" expr | block ) ;
field_inits = "{" { ident ":" expr [","] } "}" ;
match       = "match" expr "{" { pattern [ "if" expr ] "=>" ( expr | block ) [","] } "}" ;
pattern     = "_" | ident | int | float | string | "true" | "false" | "-" ( int | float )
            | ("Some" | "Ok" | "Err") "(" pattern ")" | "None"
            | Ident "." Ident [ "(" pattern { "," pattern } ")" ] ;
```

* In the conditions of `if`/`while`/`for`/`match` and in contracts a record literal `Name { ... }` is not allowed (as
  in Rust), so that `{` always starts a block.
* `if` is a statement, not an expression; to choose a value write `match cond { true => a, false => b }`.
* There are no nested named functions and no top-level variables (use lambdas and `const`).
* A negative literal as a method receiver needs parentheses: `(-5).abs()`.
* A `match` arm with a block has type `Unit` unless the block returns from the function.
* All `use` lines come first in a file, before the other declarations.

## 3. Types

| Type | Values | Notes |
|---|---|---|
| `Int` | arbitrary-precision integers | `/` truncates toward zero, `%` has the sign of the dividend; no overflow |
| `Float` | IEEE-754 double | `%` is the remainder with the sign of the dividend (`-7.5 % 2.0 == -1.5`); bits: `x.to_bits()` (Int), `float_from_bits(n)` |
| `Bool` | `true`, `false` | |
| `Str` | Unicode strings | immutable; indexes and lengths count characters (code points) |
| `Bytes` | `bytes_of([1, 255])`, `s.to_bytes()` | immutable bytes 0..255; `push`/`set` in a loop `b = b.push(x)` write in place; `read_bytes`/`write_bytes` |
| `Unit` | `()` | the result of functions without `->` |
| `Never` | — | the type of `fail(...)`, `todo(...)`, `exit(...)`; compatible with every type |
| `List[T]` | `[a, b]` | immutable |
| `Map[K, V]` | `Map { k: v }` | a key is any value without functions (compared with `==`); iteration in insertion order; `==` on maps ignores the order |
| `Option[T]` | `Some(v)`, `None` | |
| `Result[T, E]` | `Ok(v)`, `Err(e)` | |
| `fn(A) -> R` | lambdas, functions | functions cannot be compared |
| `type X {..}` | `X { f: v }` | nominal record; may be generic: `type Box[T] { value: T }` |
| `enum E {..}` | `E.V`, `E.V(f: v)` | nominal sum; may be generic and recursive |
| `type A = B` | — | transparent alias |
| `type M = new B` | `M(v)` | newtype: a distinct nominal type over `B`, its value is `m.value` |

**Newtypes.** `type Meters = new Float` declares a new type: `Meters` and `Float` are not interchangeable (E0202 with
the hint "wrap it: `Meters(value)`" or "read `.value`"). It is a record with one field `value`, but only its
constructor `Meters(x)` (or `Meters(value: x)`) builds one: the literal `Meters { value: x }` and `m with { ... }` are
E0217. `requires` lines after the declaration are the type's invariant, a precondition of the constructor: every
`Percent` value of `type Percent = new Int` + `requires value >= 0` + `requires value <= 100` has been checked (R0002 at
run time, E0703 at compile time when the argument is known). A newtype may be generic (`type Id[T] = new Int`: `Id[User]`
and `Id[Order]` do not mix), have `impl`s and be `pub`; `use m.{Meters}` imports both the type and the constructor. It
prints like a record: `Meters { value: 3.5 }`. A newtype with `requires` cannot be a `property` input (E0605: random
values would break the invariant) — generate the wrapped value and build the newtype inside.

Prelude (always available): `Pair[A, B] { first, second }`, `Entry[K, V] { key, value }`, `Indexed[T] { index, value }`,
the constants `PI` and `E`.

**Type inference.** Parameters and (unless `Unit`) function results must be annotated. Everything else is inferred by
unification; empty collections are annotated (`let xs: List[Int] = []`). Generic parameters (`[T]`) are rigid inside a
function body: such values can only be compared for equality, passed on, converted with `.to_str()` and used with the
methods of their bound's traits (`[T: Shape]`).

**Traits.** `trait T { ... }` lists methods (the first parameter is always `self`, of type `Self`). A method with a
body is a default method. `impl T for X` is written for `Int`, `Float`, `Bool`, `Str`, `Bytes` and your own
`type`/`enum`. It must define every method without a body with the same names and parameter types (`Self` = `X`), the
same result and no wider effects (E0221). For a generic type the `impl` is generic too and covers all its instances:
`impl[T: Show] Show for List[T]`, `impl[K, V] Show for Map[K, V]`, `impl[T] Show for Box[T]` — the target's arguments
are exactly the impl's parameters, each once (E0221; there are no specializations like `impl Show for List[Int]`). The
bounds of an impl's parameters hold inside its methods and at use: `List[X]` implements `Show` only if `X` does (E0220
with a hint naming the missing `impl`). There is at most one `impl` per (trait, type) pair in a program, and it lives in
the trait's module or the type's module (E0222). A bound `fn f[A: T + U](...)` allows calling the methods of `T` and
`U` on values of type `A`; when `f` is called the type argument must implement the traits (E0220) and must be
inferable (E0223). A trait is not a type (E0224): for values of different kinds use an `enum` with an `impl` for it. A
trait's methods are visible on a value when the trait is imported into the module (as in Rust), and they are called
with a dot only. The native compiler specializes a generic function for each set of types and calls the
implementation directly; the interpreter picks the implementation by the value's type; the result is the same.

**Equality.** `==` is structural. Values that contain functions (functions themselves, and records, lists, `Option`s
with functions inside) cannot be compared (E0211). `<`, `>`, `<=`, `>=` are defined for `Int`, `Float`, `Str` (E0211
otherwise); `sort`, `min`, `max` for lists of them (E0215; records via `sort_by`).

## 4. Semantics

* **Immutability.** All values are immutable. `let` binds a name once, `var` may be reassigned. Record fields are
  never assigned; update with `rec with { f: v }`. Collection methods return new values (`xs = xs.push(1)`).
* **Scopes.** Block scopes. Shadowing any visible name (function names included) is E0102. Type names are unique in the
  whole program.
* **Return.** An explicit `return` on every path (E0205). A path ends when it ends in `fail(...)`, `todo(...)`,
  `exit(...)`, a `while true` without `break` in its body (even in a nested loop), or a `match` all of whose arms end.
* **Calls.** Positional arguments, then named ones. User functions with 3 or more parameters take named arguments
  only (E0208).
* **Method syntax (UFCS).** `x.f(a)` is looked up as: (1) a function field of a record, (2) a built-in method of the
  type, (3) a trait method (of the `impl` for `x`'s type or from a type parameter's bound), (4) a user function `f`
  whose first parameter accepts `x`'s type.
* **Lambdas** capture `let` values (by copy) but not `var`s (E0216). A lambda inherits the effects of the enclosing
  function. `?` and `return` inside a lambda leave the lambda, not the enclosing function.
* **Loops.** `for x in xs` iterates over a `List` only (E0202: for a map `m.keys()`, for a string `s.chars()`);
  `range(a, b)` is the list `a..b-1`. `break`/`continue` only inside a loop (E0213).
* **`?`.** `Some(v)?`/`Ok(v)?` → `v`; `None?`/`Err(e)?` → an immediate `return` of that value. The error type must be
  the function's error type (E0212). In a test it fails the test (R0008). In a `main` with `-> Result` an `Err` ends
  the program (R0007).
* **Contracts.** `requires` is checked on entry, `ensures` on exit (the name `result`). Pure, without `?`. A violation
  is R0002/R0003 with the condition's text and the variables' values. Simple contracts (comparisons of a parameter or
  of `result` and its `len()` with a number literal, `is_empty()`, `not`, `and`) are also checked at compile time by a
  sign analysis: a call where the known signs of the argument contradict `requires` is E0703 (`if n <= 0 { sqrt_int(n) }`
  with `requires n >= 0`); a `return` whose value contradicts `ensures` is E0706. The compiler need not prove contracts:
  it reports an error only when the violation is certain.
* **Safety before running.** Integer `a / b` and `a % b` compile only when `b` is provably non-zero (E0701: a non-zero
  literal or constant, a check `b != 0` earlier on the path, `requires`, `assert`, the `ensures` of the function that
  produced `b`, and so on). A function that calls itself on every path is E0702. Calls with constant arguments are
  checked against `requires` (E0703) and the domains of built-in functions (E0704).
* **Effects** (`io`, `time`, `rand`, `fs`, `net`, `proc` — running other programs). A function's effects must include
  the effects of every function it calls by name (E0401); an unknown effect is E0403. Function types (`fn(A) -> R`)
  carry no effects: a lambda's effects are checked where the lambda is written (against the enclosing function's
  effects), so a function without `uses` does no effects itself and can only cause them by calling a function value
  it was given. Contracts and constants are pure. Tests and properties may use `io` only.
* **Parallelism.** `xs.par_map(f)` has the value of `xs.map(f)` (elements and order). The argument is a lambda that
  uses no effects (its body is checked with an empty effect set, nested lambdas too; otherwise E0401) or the name of a
  function without `uses` (otherwise E0406); any other expression of function type is E0406, because its effects are
  unknown. Inside that lambda, function values from outside it — captured variables and its parameters that contain
  functions — cannot be used (E0406): their effects are not visible. The result type `U` must not contain functions,
  not even inside records, variants, lists and maps (E0406). A runtime error inside `f` is reported as `map` would
  report it: for the first element, in order, on which `f` fails. The language has no other way to share data between
  threads of execution, so data races are impossible.
* **Ignored values.** A discarded `Result` is E0402; a discarded result of an "updating" call (by method name: `push`,
  `set`, `concat`, `filter`, `map`, `sort`, `with`, …) is E0405; other non-`Unit` values give W0401 (except
  `dbg(...)`). Discard explicitly with `let _ = expr`.
* **Matching.** `match` is exhaustive (E0301), checked through nested patterns (`Some(true)`, `Some(false)`, `None`
  cover `Option[Bool]`). `Int`, `Float` and `Str` need a `_` or a name arm. An arm covered by the earlier ones is
  warning W0303. An arm with a guard (`pattern if cond => ...`) does not count for exhaustiveness.
* **Evaluation order.** Left to right; `and`/`or` short-circuit.
* **Determinism.** Without the effects `time`/`rand` (and without reading the outside world through
  `io`/`fs`/`net`/`proc`) a program is deterministic.
* **Constants.** `const NAME: T = expr` is evaluated once before `main`; the expression is pure.
* **Entry point.** `fn main()` or `fn main() -> Result[Unit, E]` (with the `uses` it needs). `exit(code)` ends the
  program with `code` clamped to 0..255 (output is flushed). Recursion is limited to 10 000 nested calls (R0006).
* **Traits and methods.** An `impl` method repeats the names and types of the trait method's parameters; it cannot be
  named like a built-in method of the type (or `to_str`) (E0221).

## 5. Tests

```klar
test "description" {
  let x = compute(2)?          // Err/None → the test fails (R0008)
  assert x == 4                // on failure: left = ..., right = ...
  assert x > 0, "must be positive"
}
```
```klar
/// Doubles a number.
/// >>> assert double(21) == 42
fn double(x: Int) -> Int { return x * 2 }

property "reverse twice is identity" (xs: List[Int]) {
  assert xs.reverse().reverse() == xs
}
```
Doc-tests (`/// >>>`, also on trait and `impl` methods) are tests. A `property` runs on 100 random inputs (`--runs`,
`--seed`; the default seed 0 makes runs reproducible; `klar dev` uses 50); inputs are generated from the parameter
types (numbers, strings, lists, maps, `Option`, `Result`, records, `enum`s — recursive ones too; a type that cannot be
generated is E0605); on failure (R0010) the minimal counterexample after shrinking is printed; the same `--seed` gives
the same inputs in every implementation. `klar test file.klar [-k filter] [--json]`. `print` output inside a test is
shown only when it fails. `exit()` inside a test fails it (R0013).

## 6. Modules and packages

* **Modules.** `use a.b.{x, Y}` loads `a/b.klar` next to the file (or a standard module `std.*`). Imports are explicit
  only, cycles are not allowed (E0602). Only `pub` declarations can be imported (E0606); the prelude is visible in
  every module. A private function that nothing in its module calls is W0406. An `impl` is visible wherever its trait
  is.
* **Packages.** A project is a directory with `klar.toml` (searched upwards from the main file): `[package]` (`name`,
  `version`, `description`, `authors`, `license`) and `[dependencies]` of the form `name = { path = "..." }` or
  `name = { git = "...", tag|rev|branch = "..." }`; the format is a subset of TOML (strings, integers, `true`/`false`,
  inline tables, string arrays, `#` comments), errors are E0610. When the first part of a `use` is a dependency of the
  package the file belongs to, `use d.{x}` loads `<d>/lib.klar` and `use d.a.b.{x}` loads `<d>/a/b.klar`; the
  dependency's modules are named `d`, `d.a.b`. A dependency is a directory with `klar.toml` (otherwise E0609; git
  dependencies live in `<project>/.klar/deps/<name>`, put there by `klar fetch`, with the commits pinned in
  `klar.lock`). A name that is both a dependency and a file next to it is E0607; one name with different sources in
  different manifests is E0608.

## 7. Diagnostic codes

`E00xx` — lexical and syntax, `E01xx` — declarations and names, `E02xx` — expressions and types, `E03xx` — `match`,
`E04xx` — effects and values, `E05xx` — the program, `E06xx` — modules and packages, `E07xx` — compile-time safety and
contract checks, `Wxxxx` — warnings, `Rxxxx` — runtime errors. The full list with explanations and examples:
`klar explain <code>` (`klar/diagnostics.py`). Division by zero: for `Int`, a divisor that may be zero is E0701 at
compile time; for `Float`, the literal `0.0` is E0701 and a computed zero is R0001 at run time. A runtime error prints
the code, the place, the values of the condition's variables and the Klar call stack; machine-readable with `--json`.

## 8. Standard library

`klar spec` generates the full list with signatures (from `klar/builtins.py`); `klar doc <name>` shows examples for
each name.

* **Global functions:** `print`, `print_raw`, `eprint`, `read_line`, `read_exact`, `cli_args`, `dbg`, `fail`, `todo`,
  `exit`, `range`, `bytes_of`, `float_from_bits`, `now_ms`, `now_ns`, `random_int`, `env_var`, `read_file`,
  `write_file`, `read_bytes`, `write_bytes`, `file_exists`, `is_dir`, `list_dir`, `make_dir`, `remove_file`,
  `current_dir`, `set_executable`, `run_command`, `run_capture`, `Some`, `Ok`, `Err`.
* **Methods** exist on `Int`, `Float`, `Str`, `Bytes`, `List`, `Map`, `Option`, `Result`; every value has `.to_str()`.
* **Modules written in Klar:** `std.math`, `std.text`, `std.list`, `std.result`, `std.set`, `std.json`, `std.time`.

Failures of the outside world are values, not crashes: files, directories and running programs return `Result`,
`read_line` and `env_var` return `Option`. Only `fail`, `todo` and `exit` end a program abruptly.

## 9. Execution model

The semantics is the same on every backend (checked by differential tests):

* **native** (the default of `klar run` and `klar build`; the only one `klarc` builds): machine code without
  dependencies — x86-64 Linux (ELF), x86-64 Windows (PE, `kernel32.dll` only), AArch64 Linux (ELF) and,
  **experimentally**, x86-64 macOS (Mach-O: a static executable without dyld, BSD system calls; the `--target macos`
  target is chosen only explicitly). On Linux and macOS `par_map` hands chunks of the list to worker processes (fork,
  one per core, at most 64); on Windows it runs as `map`;
* **--py**: compilation to Python bytecode (a fallback);
* **--interp**: the reference interpreter (`klar test` and `klar profile` use it by default).

`Int` grows into big numbers automatically; memory is freed by reference counting (immutable values cannot form
cycles). Runtime errors print the code, the place, the values and the Klar call stack.

## 10. Implementations and conformance

* `klar` (Python) — the reference interpreter and type checker, a compiler to machine code, and the tools.
* `klarc` (Klar, `compiler/`) — the same language and the same tools written in Klar; it builds itself
  (`build.sh`, `build.bat`).

`tests/selfhost.py` checks that `klarc` produces byte for byte the same executables and the same diagnostics as
`klar`; `tests/bootstrap.py` that `klarc` reproduces itself; `tests/native_diff.py` that machine code behaves like the
interpreter (Windows executables under wine, AArch64 under qemu, macOS under the emulator `tests/macho_run.py`).
