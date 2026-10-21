# Contributing to Klar

Thanks for helping! Klar is a language designed to be written, read and verified by AI models, and it must stay
**fast**, **safe at compile time** and **identical on every back-end**.

## Setup

Python 3.10+ is the only requirement (no dependencies). From the repository root:

```sh
python -m klar run examples/hello.klar        # or: pip install -e .  →  klar run ...
python -m unittest discover -s tests          # compiler test-suite
python tests/native_diff.py                   # native back-end == reference interpreter
python tests/native_diff.py --windows         # same for .exe (Linux host needs wine)
ruff check klar tests bench                   # lint
```

## Repository layout

| path | contents |
|---|---|
| `klar/lexer.py`, `parser.py`, `nodes.py` | syntax → AST |
| `klar/checker.py`, `types.py`, `loader.py` | names, types, effects, modules |
| `klar/safety.py` | compile-time safety analysis (E07xx) |
| `klar/interpreter.py`, `builtins.py` | reference interpreter + standard library (Python side) |
| `klar/codegen.py` | Klar → Python back-end |
| `klar/native/` | native compiler: `lower` (AST→KIR), `opt`, `regalloc`, `emit` + `x64`, `link`, `build` |
| `klar/rt/*.klar` | native runtime, written in system Klar |
| `klar/std/*.klar` | standard modules written in Klar |
| `tests/` | unit tests, `stdlib/` and `native/` Klar test files, differential runner |
| `bench/` | speed benchmark; `bench/ai/` AI-ergonomics benchmark |
| `docs/` | architecture, specification, feature analysis (Russian) |

## Rules for changes

1. **Every back-end must agree.** A new built-in needs: a signature + implementation in `builtins.py`,
   support in `codegen.py` (or an `Unsupported` fallback) and a runtime function in `klar/rt/` named
   `Owner_method` / `b_name`. Add a test to `tests/stdlib/builtins_test.klar`; `native_diff.py` must stay green.
2. **Diagnostics are an API.** New errors get a stable code in `klar/diagnostics.py` (`klar explain` text included),
   a precise span, a `hint`, and a `fix` when one is mechanical (`"safe": false` if it changes meaning).
3. **Prefer compile time.** If a run-time error can be ruled out statically, do it in `safety.py` or the checker.
4. **Performance changes come with numbers** from `bench/run_bench.py` (before/after, same machine).
5. Keep the AI reference (`klar/ai_reference.md`, printed by `klar spec`) short and up to date.

## Commits and pull requests

- One logical change per commit; imperative subject line (`Add E0705 for always-out-of-bounds index`).
- Run the test-suite and `native_diff.py` before opening a pull request; CI runs them on Linux and Windows.
- Update `CHANGELOG.md` under "Unreleased" for user-visible changes.
