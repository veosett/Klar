# Working on the Klar compiler (instructions for AI assistants)

Klar is a language for AI authors: fast (own x86-64 compiler and linker), safe at compile time, and identical on
every back-end. Read `CONTRIBUTING.md` for the full rules; the essentials:

## Before you finish any change
```sh
python -m unittest discover -s tests        # front-end, 3 back-ends, tools, compile-time safety
python tests/native_diff.py                 # native back-end == reference interpreter (19 files)
python -m klar fmt --check .                # Klar code in canonical form
ruff check klar tests bench                 # lint
```

## Where things are
- `klar/checker.py` types/effects · `klar/safety.py` compile-time safety (E07xx) · `klar/diagnostics.py` error catalog
- `klar/interpreter.py` + `klar/builtins.py` reference semantics · `klar/codegen.py` Python back-end
- `klar/native/` native compiler (`lower` → KIR → `opt` → `regalloc` → `emit`/`x64` → `link`) · `klar/rt/*.klar` runtime in Klar
- `klar/tools/` developer tools (fmt, outline, doc, refs, rename, eval, coverage, view, new)
- `klar/ai_reference.md` is what `klar spec` prints — keep it short and current

## Rules
1. A new built-in needs the interpreter implementation, Python back-end support (or `Unsupported`) and a runtime
   function in `klar/rt/` (`Owner_method` / `b_name`), plus a test in `tests/stdlib/builtins_test.klar`.
2. New errors get a stable code with `explain` text, a precise span, a hint, and a fix when mechanical.
3. Prefer rejecting mistakes at compile time over run-time errors.
4. Performance changes come with `bench/run_bench.py` numbers.
5. Commit in small steps with imperative messages; update `CHANGELOG.md` (Unreleased).

## Writing Klar code (examples, std, tests)
Use the tools instead of guessing: `klar spec`, `klar doc <name>`, `klar eval '<expr>'`, `klar outline <file>`,
`klar dev <file> --json`.
