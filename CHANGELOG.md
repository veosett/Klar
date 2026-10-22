# Changelog

All notable changes to Klar. The format follows [Keep a Changelog](https://keepachangelog.com/),
versions follow [Semantic Versioning](https://semver.org/) (pre-1.0: minor versions may break things).

## [Unreleased]

### Added
- Packages: a project is a directory with `klar.toml` (`[package]`, `[dependencies]` with `name = { path = "..." }` or
  `name = { git = "...", tag|rev|branch = "..." }`). The first part of a `use` may name a dependency:
  `use geo.{Point}` loads `<geo>/lib.klar`, `use geo.shapes.{Circle}` its `shapes.klar`; a dependency's modules are
  named after it, so they never clash with the project's. `klar add`, `klar remove`, `klar fetch` (git dependencies
  into `.klar/deps/`, commits pinned in `klar.lock`), `klar update`, `klar deps`; `klar new` writes `klar.toml`,
  `klar new --lib` a library package. New errors: E0607 (a name is both a dependency and a file), E0608 (one name,
  different sources), E0609 (dependency not fetched / not a package), E0610 (invalid klar.toml). Both compilers
  resolve dependencies the same way: `compiler/manifest.klar` reads the manifests for `klarc`.

## [0.7.0] — 2026-10-22

Safer types and safer edits: generic impls, newtypes with invariants, contracts checked at compile time, and a patch
protocol that lets an AI change code by name and keeps only edits that still compile and pass the tests.

### Added
- `klar patch FILE PATCH` — the "AI patch" protocol: structured edits addressed by declaration name (`area`,
  `Circle.area`, `test:name`), by node id (`klar ast`) or by unique text, plus renames; all edits apply to the original
  text together, the result is formatted and checked (and tested with `--test`), and the file is written only when
  nothing new breaks. `--dry-run`, `--force`, `--json` (diff, errors, test results).
- `klar ast` numbers nodes per file (stable ids, pre-order from 1).
- Generic impls: `impl[T: Show] Show for List[T]`, `impl[K, V] Show for Map[K, V]`, `impl[T] Show for Box[T]` — for
  List, Map, Option, Result and generic `type`/`enum` declarations. An impl covers every instance; its bounds apply
  inside its methods and are checked recursively at use (`List[Box[Str]]: Show` needs `Str: Show`, E0220 names the
  missing piece). All back-ends dispatch statically (native: the impl's type parameters come from the receiver's
  type), in both the Python and the self-hosted compiler. `klar outline` shows impl headers as written.
- Newtypes: `type Meters = new Float` declares a distinct type (no mixing with `Float` or other newtypes; E0202 hints
  "wrap the value: `Meters(value)`" / "read the wrapped value: `.value`"). It is built only by its constructor
  `Meters(x)` — a function the parser adds after the declaration — whose `requires` lines are the type's invariant
  (`type Percent = new Int` / `requires value >= 0 and value <= 100`): checked at run time (R0002) and at compile time
  for known arguments (E0703). Record literals and `with` on a newtype are rejected (E0217). Generic newtypes
  (`type Id[T] = new Int`), impls and `pub` work; `use m.{Meters}` imports the type and its constructor.
- Static checking of simple contracts: a `requires` that compares a parameter (or its `len()`) with a number literal,
  `is_empty()`, `not` and `and` is checked against the signs the safety analysis knows at each call — `if n <= 0 {
  root(n) }` with `requires n >= 0`, `first([])` with `requires not xs.is_empty()` are E0703 — and the same kind of
  `ensures` against every `return` (E0706: `ensures result >= 0` and `return -1`). Errors only when the violation is
  certain; newtype invariants are checked the same way.

## [0.6.0] — 2026-10-22

Self-hosting: the whole compiler is written in Klar (`compiler/`, ~22 000 lines) and builds itself — byte-identical
to the Python implementation at every stage, from tokens to executables, and faster than it.

### Added
- Self-hosting, stage 3a: `compiler/lexer.klar` — the lexer written in Klar. `tests/selfhost.py` checks that it
  produces exactly the tokens (kinds, values, spans, string parts) and the errors of `klar/lexer.py` on every
  `.klar` file of the repository and on error snippets (native and interpreter runs, in CI).
- Self-hosting, stage 3b: `compiler/ast.klar` (the syntax tree as Klar enums and records) and
  `compiler/parser.klar` — the recursive-descent parser written in Klar, with doc-tests, string interpolation,
  traits and impls. `tests/selfhost.py` compares its tree (every node and span, via `compiler/dump_ast.klar`) and
  its syntax errors with `klar/parser.py` on every repository file and on 100 error snippets; the parser also
  parses its own source.
- Self-hosting, stage 4a: the checker and the module loader in Klar — `compiler/types.klar` (types and unification
  without mutation), `compiler/checker.klar` (names, types, effects, traits and impls, exhaustiveness, lints),
  `compiler/loader.klar` (prelude, `use`, std, cycles, private items) and `compiler/similar.klar` ("did you mean"
  exactly like Python's `difflib`). `tests/selfhost.py` compares every diagnostic (code, message, hint, position) with
  klar/checker.py on every repository file and on the ~210 programs of `tests/selfhost_cases.txt`.
- Self-hosting, stage 4b: the safety analysis in Klar (`compiler/safety.klar`: E0701–E0705, E0215 — sign analysis,
  facts from conditions, `var` summaries, contracts, unconditional recursion). The Klar checker now records the static
  type of every expression and how each method call was resolved, and `tests/selfhost.py` compares those too.
- Self-hosting, stage 4c: the native backend's middle in Klar — `compiler/lower.klar` (typed AST -> KIR with
  monomorphization, reference counting, closures, contracts, the data image), `compiler/opt.klar` (coalescing,
  folding, compare-and-branch fusion, dead code, inlining) and `compiler/regalloc.klar` (linear scan with GPR and XMM
  classes). `tests/selfhost.py` compares the KIR, the data image (byte for byte) and the register allocation of
  every program with a `main` — 23 programs, ~790 000 KIR instructions, the Klar compiler itself included.
- Self-hosting, stage 4d: the x86-64 emitter and the linkers in Klar — `compiler/x64.klar` (the assembler),
  `compiler/emit.klar` (KIR -> machine code: tagged-Int fast paths with out-of-line slow paths, XMM floats, x87,
  division by constants, the Linux and Windows OS layers, the trace tables) and `compiler/link.klar` (ELF64 and
  PE32+ writers). `tests/selfhost.py emit` checks that the executables built by the Klar backend are byte for byte
  those of `klar build`, for Linux and Windows, for every program with a `main` (the Klar compiler included).
- Self-hosting, stage 5 — bootstrap: `compiler/klarc.klar`, the command-line compiler written in Klar
  (`klarc build app.klar [-o out] [--target linux|windows] [--lib dir] [--time]`, `klarc check app.klar`). Built by
  the Python compiler it builds itself, and the result builds itself again: stage1 == stage2 == stage3, byte for
  byte (`tests/bootstrap.py`, also in the unit tests on Linux).
- Native: "functional but in place" across function calls. Parameters a function consumes are passed owned
  (inferred over the call graph), the last use of a local moves its value (path-wise liveness: `w`, `w.img`,
  `a.w`), a field of a unique record is taken out instead of shared, and `x with { f: x.f.push(v) }` reuses a unique
  record and updates the field in place (`klar/native/own.py`, `compiler/own.klar`). `Bytes.concat` and `push`/`set`
  on temporaries update in place too. The self-hosted compiler builds itself in 8 s instead of 35 s.
- `tests/native/ownership.klar`: unique and shared values through calls, records, closures and `match`.
- `run_command(["prog", "arg"]) -> Result[Int, Str]` (new effect `proc`): runs a program found in `PATH` with
  inherited stdin/stdout/stderr and returns its exit code — fork/execve/wait4 on Linux, `CreateProcessA` on
  Windows, `subprocess` in the interpreter. `set_executable(path)` (`fs`): chmod 755 (nothing to do on Windows).
- `klarc run app.klar [-- args]` and `klarc test app.klar`: the self-hosted compiler builds into a temporary file
  and runs the program, or builds the `test` blocks and runs each one in its own process (PASS/FAIL, summary, exit
  code). The test-executable lowering is now in Klar too; `tests/selfhost.py` compares it with the Python one.
- `Float.to_bits()` and `float_from_bits(bits)`: the IEEE-754 bits of a Float as a signed 64-bit Int, and back
  (the Klar backend needs them for float constants).
- The Klar loader loads the runtime (`klar/rt`, one module of several files); the Klar checker records what the
  backend needs (the type arguments of every call, the element type of every `for`).
- The Klar parser reports the same hints as the Python one, and the parser comparison now covers every `*_span`.

### Changed
- CI runs only on demand (`workflow_dispatch`).

### Fixed
- Native: constants holding lists or maps corrupted the heap (they were built before the runtime's own constants
  were initialised); the runtime's constants are now initialised first.
- Klar parser: `-0.0` was folded to `0.0`; the parser comparison now compares Floats by their bits.
- Register allocation no longer depends on the iteration order of Python sets when two intervals are equal (ties
  are broken by the vreg number): builds are deterministic regardless of the Python implementation.
- Instance names of generic functions use a stable FNV-1a hash of the type instead of Python's `hash`.
- Checker: a constant declared twice crashed the checker; it is now reported once (E0101) and skipped.
- Checker: E0216 (a lambda capturing a `var`) could be lost for a second lambda, depending on Python object ids;
  it is now reported once per variable and lambda.
- `klar fmt` refused files where a re-indented line contained an interpolated string (the check compared the
  positions of the interpolated code, which legitimately move).

## [0.5.0] — 2026-10-21

### Added
- Windows is a first-class CI target: the whole test-suite and the native/interpreter comparison pass with
  Windows Python (checked with Python 3.12 for Windows), so the Windows jobs are no longer allowed to fail.
- `Bytes`: an immutable byte sequence (`bytes_of`, `Str.to_bytes`, `len`, `get`, `get_or`, `slice`, `concat`, `push`,
  `push_le`, `set`, `to_list`, `decode`, `hex`) with `read_bytes` / `write_bytes`. `b = b.push(x)` appends in place in
  native code when `b` is the only reference. Constant bytes out of 0..255 and bad `push_le` sizes are compile-time
  errors (E0704). Property tests generate and shrink `Bytes`.
- Faster calls in native code: the call depth (R0006 above 10000, exactly as in the interpreter) lives in the
  reserved register R15 instead of a global (`fib` 1.0 → 0.68 ms); values may stay in caller-saved registers
  across calls (saved around them); calls inside inlined runtime accessors are cold, so floats stay in XMM
  registers across them. The native R0006 message names the function, like the interpreter.
- `klar repl`: an interactive session. Every input is type-checked with the whole session (same rules as a
  program); only new statements run, variables persist; `:type`, `:doc`, `:load`, `:defs`, `:reset`.
- Language server `klar lsp` (LSP over stdio, no dependencies): diagnostics as you type with quick fixes (including
  fixes in another module), hover with types/signatures/docs, go to definition across modules, references and
  rename (locals stay inside their function), completion of names and of `.` members, signature help, document
  symbols (traits and impls with their methods), formatting. `KLAR_LSP_LOG=<file>` logs the session.
- The VS Code extension starts the server (`klar.pythonPath`, `klar.compilerPath` settings) and adds commands to
  run, test and `klar view` the current file; an end-to-end test drives a real VS Code in CI.

## [0.4.0] — 2026-10-21

### Added
- `std.json`: `Json` enum (exact `Int` numbers, ordered objects), `parse_json` with line/column errors,
  `json_text`, `json_pretty`, `field` / `item` / `lookup("a.0.b")`, `as_*` accessors and builders.
- `std.time`: `DateTime` in UTC, `from_unix_ms` / `to_unix_ms`, `now_utc`, ISO 8601 `format_iso` / `parse_iso`,
  `weekday`, `day_of_year`, `add_days`, `days_between`, leap years — pure calendar arithmetic, valid before 1970.
- `List.get_or(index, default)`: an element without allocating an `Option`.

- Native code keeps floats in XMM registers (XMM2–XMM15, a second register class in the linear-scan allocator);
  Int slow paths save them, so float loops with Int counters stay in registers. `mandelbrot`: 1.1 ms → 0.33 ms
  (C: 0.27 ms, Go: 0.25 ms).
- Visibility: only `pub fn` / `pub type` / `pub enum` / `pub const` / `pub trait` can be imported (E0606, with a
  `klar fix` that adds the `pub` in the other module); a private function nothing calls warns (W0406). The
  standard modules mark their API `pub`. **Breaking:** modules imported by others need `pub` on what they share.
- Exhaustiveness of nested patterns (usefulness algorithm): `match` reports the exact missing values
  (`Some(Shape.Rect(_, _))`, `Ok(None)`, ...), accepts complete nested matches without a catch-all, and warns
  about every unreachable arm, not only those after a catch-all.
- Traits: `trait Name { fn m(self, ...) -> T }` with default methods, `impl Name for Type` (Int, Float, Bool, Str
  and non-generic records/enums), bounds on generic functions `fn f[T: A + B](x: T)` and the `Self` type.
  Checked statically (E0220 not implemented, E0221 impl does not match, E0222 impl misplaced/duplicated,
  E0223 type not inferable, E0224 trait used as a type); `klar fix` inserts `todo(...)` stubs for missing
  methods. The native compiler dispatches statically (one instance per type); the interpreter and the
  Python back-end dispatch on the runtime type. Tools (`outline`, `doc`, `refs`/`rename`, `view`) know traits.
- The compile-time contract check (E0703) also covers method-syntax calls (`x.f(...)`, impl methods).
- Bit operations on Int (`bit_and`, `bit_or`, `bit_xor`, `bit_not`, `shift_left`, `shift_right`; two's complement,
  arbitrary precision), `Str.codes` / `Int.to_char`, `exit(code)`, `env_var(name)`, and `std.set` (`Set[T]`).
  The lexer points `& | ^ ~ << >>` at the methods. All back-ends agree (native on Linux and Windows).
- Developer tools (`klar/tools/`, documented in `docs/TOOLS.md`):
  `klar fmt` (canonical layout, token-stream safety net, `--check`/`--diff`), `klar outline` (API of a file),
  `klar doc` (built-ins, std and project symbols with tested examples), `klar eval` (value : type of an expression),
  `klar refs` / `klar rename` (exact thanks to no shadowing), `klar coverage` (statements tests never run),
  `klar view` (interactive HTML for human reviewers: overview, call graph with run counts, step-by-step flow of each
  function, EN/RU), `klar new` (project skeleton with `AGENTS.md`).
- VS Code extension (`editors/vscode`): highlighting, snippets, problem matcher.
- E0216: a lambda may not capture a `var` (snapshot it with `let`, or use `fold` / a `for` loop) — removes the
  "does the closure see later changes?" class of bugs; the native back-end now compiles every valid program.
- Clear error with a fix for `fn(x) => { ... }` (a block-bodied lambda has no `=>`).
- Illustrated language guides with diagrams: `docs/GUIDE.md` (Russian), `docs/GUIDE.en.md` (English); every code
  example in them is compiled and tested by the test-suite. Architecture diagrams converted to Mermaid.
- `AGENTS.md` / `CLAUDE.md` for AI assistants working on the repository.

### Changed
- `now_ms()` is the wall clock (ms since 1970 UTC) on every back-end; the native build used a monotonic clock.
  `now_ns()` stays monotonic for measuring durations.

## [0.3.0] — 2026-10-21

### Added
- **Native compiler** (`klar/native/`): Klar → KIR → optimizer → linear-scan register allocator →
  own x86-64 assembler → own linker writing ELF64 (Linux, raw syscalls, no libc) and PE32+ (Windows, KERNEL32 only).
  `klar run` uses it by default; `klar build [--target linux|windows]` writes a standalone executable.
- **Runtime written in Klar** (`klar/rt/*.klar`): allocator, reference counting, bignums, shortest Float printing,
  UTF-8 strings, List, Map, I/O.
- Optimizer: inlining of small runtime functions, constant folding into immediates, address folding,
  copy propagation and coalescing, compare-and-branch fusion, division by constants via reciprocal multiply,
  dead and unreachable code elimination. In-place updates for uniquely referenced values.
- Zero-cost error traces: frame-pointer walk + return-address tables (identical text to the interpreter).
- **Compile-time safety pass** (`klar/safety.py`): E0701 Int division without a proof that the divisor is non-zero,
  E0702 unconditional recursion, E0703 constant arguments violating `requires`, E0704 constant arguments outside a
  built-in's domain, E0705 always-out-of-bounds index, E0215 sorting values without an order.
- Better hints for using `Option`/`Result` as plain values and for lines starting with an operator.
- Speed benchmark: C++ and Rust added (C, C++, Rust, Go, Java, JS, Python, Klar ×3 back-ends).
- **AI-ergonomics benchmark** (`bench/ai/`): 13 typical AI mistakes × 7 languages.
- `tests/native_diff.py` (native vs interpreter, Linux and Windows via wine), `tests/native/edge_cases.klar`.
- Project infrastructure: `pyproject.toml` (`klar` console script), CI, license, contributing guide.

## [0.2.0]

### Added
- Modules (`use a.b.{x}`), generic records and enums, type aliases, constants, `match` guards, prelude in Klar.
- Doc-tests (`/// >>>`), property tests with shrinking, `dbg`, `todo`.
- Tools: `klar dev` (one AI-loop step, compact JSON), `klar fix` (safe machine fixes), `klar profile`.
- Back-end compiling Klar to Python bytecode; standard modules `std.math`, `std.text`, `std.list`, `std.result`.

## [0.1.0]

### Added
- Core language: static types with inference, generic functions, records, enums, `Option`/`Result`/`?`,
  immutability, effects (`uses io`), contracts (`requires`/`ensures`), exhaustive `match`, tests.
- Reference tree-walking interpreter, JSON diagnostics with stable codes, `klar spec`, `klar explain`.
