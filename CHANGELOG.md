# Changelog

All notable changes to Klar. The format follows [Keep a Changelog](https://keepachangelog.com/),
versions follow [Semantic Versioning](https://semver.org/) (pre-1.0: minor versions may break things).

## [Unreleased]

### Added
- Self-hosting, stage 3a: `compiler/lexer.klar` — the lexer written in Klar. `tests/selfhost.py` checks that it
  produces exactly the tokens (kinds, values, spans, string parts) and the errors of `klar/lexer.py` on every
  `.klar` file of the repository and on error snippets (native and interpreter runs, in CI).
- Self-hosting, stage 3b: `compiler/ast.klar` (the syntax tree as Klar enums and records) and
  `compiler/parser.klar` — the recursive-descent parser written in Klar, with doc-tests, string interpolation,
  traits and impls. `tests/selfhost.py` compares its tree (every node and span, via `compiler/dump_ast.klar`) and
  its syntax errors with `klar/parser.py` on every repository file and on 100 error snippets; the parser also
  parses its own source.

### Fixed
- Native: constants holding lists or maps corrupted the heap (they were built before the runtime's own constants
  were initialised); the runtime's constants are now initialised first.
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
