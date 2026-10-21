# Changelog

All notable changes to Klar. The format follows [Keep a Changelog](https://keepachangelog.com/),
versions follow [Semantic Versioning](https://semver.org/) (pre-1.0: minor versions may break things).

## [Unreleased]

### Added
- Developer tools (`klar/tools/`, documented in `docs/TOOLS.md`):
  `klar fmt` (canonical layout, token-stream safety net, `--check`/`--diff`), `klar outline` (API of a file),
  `klar doc` (built-ins, std and project symbols with tested examples), `klar eval` (value : type of an expression),
  `klar refs` / `klar rename` (exact thanks to no shadowing), `klar coverage` (statements tests never run),
  `klar view` (interactive HTML for human reviewers: overview, call graph with run counts, step-by-step flow of each
  function, EN/RU), `klar new` (project skeleton with `AGENTS.md`).
- VS Code extension (`editors/vscode`): highlighting, snippets, problem matcher.
- `AGENTS.md` / `CLAUDE.md` for AI assistants working on the repository.

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
