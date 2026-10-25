# Changelog

All notable changes to Klar. The format follows [Keep a Changelog](https://keepachangelog.com/),
versions follow [Semantic Versioning](https://semver.org/); what 1.x keeps compatible is listed in
[docs/SPEC.md](docs/SPEC.md), section 0.

## [Unreleased]

### Fixed
- On Windows the interpreter printed Windows' own texts for file errors ("The directory name is invalid"); it uses
  the same words as native code on every system ("Not a directory").
- `tests/selfhost.py` (and its unit test) ran the Linux build of klarc on Windows; it is skipped on hosts other than
  Linux x86-64, like `tests/bootstrap.py`.

### Security
A security review of the language, the runtime and the tools (`SECURITY.md` describes the model):
- Native code: `"x".repeat(n)` and lists sized from a huge count (`range(0, 2^61)`) overflowed the size of the
  allocation and wrote past it; every allocation size is now checked (new runtime error R0015, "out of memory", also
  in the interpreter instead of a Python exception). Printing, `==` and hashing of values nested more than 100 000
  levels deep overflowed the machine stack; they are R0006 now.
- `klarc` wrote its temporary executables to `/tmp` under predictable names (a symlink planted there by another
  user was followed); they live in `~/.klar-cache/klarc` now, and an existing file is removed before writing.
- `klar fetch` / `klarc fetch`: a git URL or revision from `klar.toml` or `klar.lock` that starts with `-` reached
  git as an option; such values are refused (and `git clone` gets `--` before the URL).
- Windows: `run_command` / `run_capture` let CreateProcessA find the program in the current directory first (a
  `git.exe` in an untrusted project would have run); the runtime now searches `PATH` itself and passes the full path.
- The language servers stopped (or crashed) on a malformed message; it is skipped now.
- The interpreter crashed with Python errors on `Float.to_int()` of infinity or NaN (now R0009, like native code) and
  on source nested thousands of brackets deep: expressions and types nested more than 200 levels are E0003 in
  `klar` and `klarc` (the Python parser also runs in a thread with a large stack: on Windows with Python 3.10 the
  test crashed the process).
- `--allow fs:DIR` could be left through a symbolic link: a link inside DIR that points outside (`data/out -> ..`)
  gave access to where it leads, and `data/out/../x` was checked as `data/x` while the system opened the file next
  to the link's target. Paths are now resolved the way the system opens them, part by part with links followed
  (`os.path.realpath`; in native code the new `os_readlink` intrinsic on Linux x86-64 and arm64 and macOS; Windows
  does not resolve links yet). In all four backends and every native target.
- The MCP tools `klar_dev` and `klar_eval` ran the model's code with every right (`main` could run programs and
  write files). They get the rights of `klar mcp --allow RIGHTS` / `klarc mcp --allow RIGHTS` now, by default
  none but `io`; `klar dev` and `klar eval` take `--allow` too. `docs/THREATS.md` lists every threat to a sandboxed
  run of a model's code with its test (`SandboxThreats` in tests/test_klar.py) and what is still open (environment
  variables, resource limits, links on Windows, programs found through PATH).

### Changed
- E0208 asks for named arguments only where they could be swapped unnoticed. With 3+ parameters, positional
  arguments are fine when the parameters have different types, or when among same-typed parameters every argument
  but at most one carries its parameter's name (`cell(grid, r, c)`, `cell(grid, nr, c - 1)`, `p.r`); `f(200, 20,
  10)` and `cell(g, i, j)` still need names, and `cell(g, c, r)` is reported as swapped. In the agent benchmark the
  old rule was half of all Klar compile failures, and 15 of its 17 calls could not have been wrong.
- What models write out of habit is accepted with the meaning they mean: `{"a": 1}` is a map (as `Map {"a": 1}`),
  `fn(x) => { ... }` a block lambda, and a `{` that cannot start an interpolation (`"{"`, `"{}"`, `"{\"a\": 1}"`)
  a literal brace — all three were errors.

### Added
- Number literals the way models write them (found by the agent benchmark, ROADMAP 20): hexadecimal, binary and
  octal integers (`0xFF`, `0b1010`, `0o17`, underscores between digits) and Floats with an exponent (`1e-9`,
  `2.5E10`), in `klar` and `klarc`, `klar fmt` (`0x1e-5` stays a subtraction) and the VS Code grammar.
  `std.math.floor_div` and `floor_mod` round like Python's `//` and `%` (Klar's `/` truncates). The `\r` escape
  is listed in the E0004 hint and the reference.
- The LLM benchmark with agents as the model (ROADMAP 20): `bench/ai/agent_bench.py` hands an agent (a Claude Code
  subagent of a given model) the same prompts, hidden tests, feedback and attempts as `llm_bench.py`, records every
  attempt and scores the run by a deterministic replay; `report` gives first-try and total rates with 95% Wilson
  intervals and exact McNemar tests between the languages. A first run — Sonnet and Haiku, HumanEval, HumanEval+ and
  the own tasks, 1 458 solutions — is in `bench/ai/results/agents/` and summed up in `bench/ai/README.md`: the
  suites are saturated, and on the first try Klar is slightly behind Python (97.7% against 99.4%, p = 0.02), mostly
  because of the named-arguments rule (E0208). HumanEval+ (`--suite humaneval_plus`, EvalPlus's extra inputs with
  its canonical results, up to 60 tests per problem) joins the suites.
- Outside task suites for the LLM benchmark (ROADMAP 19): HumanEval and MBPP as MultiPL-E ships them, turned into
  the task format of `bench/ai/llm_bench.py` by `bench/ai/build_suites.py` — 154 of 161 HumanEval and 334 of 400
  MBPP problems, 2 111 test cases, each checked against the canonical Python solution called with the typed
  arguments (which found 6 problems where MultiPL-E's typing contradicts the problem, e.g. HumanEval/92 and /151,
  and HumanEval/111's parameter `test`, a Klar keyword). `llm_bench.py --suite humaneval|mbpp`, `--validate` (every
  test file type-checks against a stub in Klar, Python and TypeScript: all do), a `Pair` type for two-element
  tuples; the references pass every test (`--provider reference -l python`).
- `tools/inventory.klar` (ROADMAP 27): the Python code of the repository from its primary sources — `git ls-files`,
  the import graph, the Klar counterpart of each module, how often both change in one commit (`git log`) and test
  coverage (coverage.py JSON) — into `docs/PYTHON_INVENTORY.md`.
- `tools/parity.klar` (ROADMAP 29): every command and flag of `klar` against `klarc`, read from the tools themselves
  (`--help`, the usage text, the compiler's literals); `tests/bootstrap.py` fails when klarc lacks one. It found
  `klarc view --open` and `klarc lsp --stdio` missing and `klarc context` absent from the usage: added.
- `tests/fuzz.klar` (ROADMAP 23, 31): differential fuzzing — random programs, well-typed by construction (Int, Bool,
  Str, List, Option, helper functions, bounded loops, lambdas, guarded division), run by the interpreter, the Python
  backend, native code from `klar` and native code from `klarc`; a disagreement or a rejected program is kept.
- The benchmark runners are written in Klar: `bench/run_bench.klar` (speed against C, C++, Rust, Go, Java, JavaScript
  and Python) and `bench/ai/run_ai_bench.klar` (when each language catches typical AI mistakes) replace the Python
  scripts; run them with `klarc run` (no Python needed) or `klar run`.
- Standard library: `std.regex` (classes, groups, alternatives, `* + ? {n,m}`, anchors: `is_match`, `find`,
  `find_all`, `replace_all`, `split_by`), `std.csv` (RFC 4180 parsing and formatting, `records`), `std.path` (`join`,
  `normalize`, `dirname`, `basename`, `extension`, `relative_to`, ...), `std.hash` (`crc32`, `fnv1a`, `sha256`),
  `std.numfmt` (`group_digits`, `percent`, `human_bytes`, `ordinal`, Roman numerals) and time-zone offsets in
  `std.time` (`at_offset`, `format_iso_offset`, `parse_iso_offset`). Every function has a doc-test; the same results in
  native code.
- **Record and replay**: `klar run --record run.json prog.klar` writes everything the run got from outside (input,
  arguments, environment, clock, random numbers, files read, results of programs run and of writes); `klar replay
  run.json` runs it again on exactly that — the same output, error and exit code byte for byte, without the files or
  the clock, and without writing anything. A replay of a changed program stops with R0017. Native too: `klarc run
  --record` and `klarc replay` build the program with a trace mode (`klar/rt/trace.klar`); the trace is the same
  JSON, so a recording made by `klar` replays in `klarc` and the other way round.
- **Contracts are tested**: `klar test`, `klar dev` and `klarc test/dev` run every pure, non-generic top-level function
  with `ensures` on random inputs that satisfy its `requires` (a generated property `contract: name`), so a contract
  finds a wrong result without a single `test`. It found one in `examples/shapes.klar`: `area` of an impossible
  triangle broke `heron`'s precondition (`area` now `requires valid(s)`).
- **Effects in function types**: `fn(Int) -> Unit uses io`. Calling a function value needs the effects of its type,
  a named function or a lambda passed as a value carries its effects, and a function with fewer effects fits where
  more are allowed. Built-ins that take a function (`map`, `filter`, `fold`, ...) need the effects of that function.
  A function without `uses` is now pure also when it calls function values, and `par_map` accepts any function value
  whose type is pure (the E0406 rule about function values from outside its lambda is gone). A function that returns
  an effectful function writes the return type in parentheses: `-> (fn(Str) -> Unit uses io)`. Example:
  `examples/effects.klar`.
- **Rights at run time**: `klar run --allow fs:./data,proc:git,time` / `klar build --allow ...` (and `klarc run/build
  --allow`) run a program with only these rights in every backend — files outside the allowed directories, other
  programs, the clock and random numbers are runtime error R0016 with the missing right; `io` is always allowed.
  Native executables carry the rights. Tested for every right in the interpreter, the Python backend and native
  code (Linux, Windows, ARM64, macOS).
- `klar context FILE NAME [--max-tokens N] [--json]` (also `klarc context` and the MCP tool `klar_context`): the
  smallest context to change one function, type or constant — its source with the documentation, the signatures of
  the declarations it uses, its tests and its callers, within a token budget (default 2000; what does not fit is
  counted as "not shown").
- **Fakes for the effects of tests**: `test "save" uses fs, time, rand { ... }` (and `property "p" (x: Int) uses fs`)
  runs on an empty file system in memory rooted at `/`, a clock that starts at 0 (new built-in `set_clock(ms)`) and
  a fixed sequence of random numbers — the same in the interpreter and in native code, fresh for every test and
  every run of a property. Calling an effect a test does not declare is E0401 with a fix that adds `uses ...`;
  `proc` and `net` stay forbidden in tests. Tested in `tests/native/fakes.klar`.
- `docs/ROADMAP.md`: the plan after 1.0 (phases, acceptance criteria, status).
- `bench/ai/llm_bench.py`: an LLM-in-the-loop benchmark — 24 tasks with hidden tests generated for Klar
  (`klar test`), Python and TypeScript (`tsc --strict`); the model gets the statement (for Klar also `klar spec`),
  sees compiler messages and failing cases and retries. It reports tasks solved on the first try and in total,
  attempts, tokens and how many failures the compiler caught before running. Anthropic and OpenAI-compatible APIs,
  `--provider reference` (the reference solutions in `bench/ai/tasks/ref/`) and `--provider replay` (re-score saved
  answers).
- `klar mcp` / `klarc mcp`: a Model Context Protocol server (stdio, newline-delimited JSON-RPC) that gives AI agents
  the Klar tools directly — `klar_check`, `klar_dev`, `klar_test`, `klar_eval`, `klar_doc`, `klar_outline`,
  `klar_refs`, `klar_patch`, `klar_fix`, `klar_fmt`, `klar_explain`, `klar_spec`. Each runs the command of the same
  name (`--json` where there is one); `klarc mcp` gives the same answer to every message (`tests/selfhost.py`
  replays a session that uses every tool). `claude mcp add klar -- python3 -m klar mcp`.
- `run_capture` on Windows: the input, stdout and stderr of the program go through temporary files and the new
  intrinsic `os_spawn_std` (CreateProcessA with STARTF_USESTDHANDLES and inheritable handles). With it every klarc
  command that runs programs works on Windows: `klarc dev`, `eval`, `view --run`, `coverage`, `profile` and the
  git dependencies of `klarc add` / `fetch`.

## [1.0.0] — 2026-10-23

The first stable version: the language of `docs/SPEC.md` (Klar 1.0), compatible within 1.x. `klarc`, the compiler
written in Klar, now has every command of `klar` and builds itself without Python from a release seed.

### Added
- Packages: a project is a directory with `klar.toml` (`[package]`, `[dependencies]` with `name = { path = "..." }` or
  `name = { git = "...", tag|rev|branch = "..." }`). The first part of a `use` may name a dependency:
  `use geo.{Point}` loads `<geo>/lib.klar`, `use geo.shapes.{Circle}` its `shapes.klar`; a dependency's modules are
  named after it, so they never clash with the project's. `klar add`, `klar remove`, `klar fetch` (git dependencies
  into `.klar/deps/`, commits pinned in `klar.lock`), `klar update`, `klar deps`; `klar new` writes `klar.toml`,
  `klar new --lib` a library package. New errors: E0607 (a name is both a dependency and a file), E0608 (one name,
  different sources), E0609 (dependency not fetched / not a package), E0610 (invalid klar.toml). Both compilers
  resolve dependencies the same way: `compiler/manifest.klar` reads the manifests for `klarc`.
- ARM64 backend: `klar build --target linux-arm64` (and the default on an arm64 host) writes a static AArch64 ELF for
  Linux. Same frames and calling convention as on x86-64 (`stp x29, x30`, arguments at `[fp+16+8i]`), X28 counts the
  call depth, floats live in D16–D31; data is reached PC-relatively (ADRP + ADD, patched by the linker); 64 KB
  segment alignment. Both compilers have it (`klar/native/a64.py`, `emit_a64.py`; `compiler/a64.klar`,
  `emit_a64.klar`) and `tests/selfhost.py` compares their arm64 executables byte for byte; `klarc build --target
  linux-arm64` cross-compiles. `tests/native_diff.py --arm64` runs every native test under qemu-aarch64.

- Parallelism: `xs.par_map(f)` — the result of `xs.map(f)`, computed on all CPU cores. In native code on Linux the
  list is cut into one chunk per core and each chunk runs in a worker process (fork; results come back through a
  pipe in a compact binary form rebuilt with the type descriptors). The checker makes it safe: `f` must be a lambda
  without effects or a function without `uses` (E0401 / new E0406), and the results must not contain functions
  (E0406). A runtime error in `f` is reported exactly like in `map` (the first failing element); the other workers
  are stopped. On Windows and in the interpreter `par_map` is `map`. New runtime file `klar/rt/par.klar`, new
  intrinsics `os_fork`, `os_pipe`, `os_wait`, `os_kill`, `os_cpu_mask` in all three OS layers of both compilers.
- `list_dir(path)` (sorted entry names, `Result[List[Str], Str]`), `is_dir(path)` (effect `fs`) and `eprint(value)`
  (print to stderr, effect `io`), in every backend (Linux: getdents64; Windows: FindFirstFileA).
- `klarc fmt [paths] [--check] [--json]`: the formatter written in Klar (`compiler/fmt.klar`); `tests/selfhost.py`
  checks that it formats every file of the repository, and a damaged copy of each, exactly like `klar fmt`. First
  step of moving all `klar` commands into `klarc`.
- `klarc check [--json]`, `klarc fix [--dry-run] [--all] [--warnings] [--json]`, `klarc explain CODE`,
  `klarc --version`: the same output as the Python commands, character for character — the Klar checker now
  produces the full diagnostics (end positions, notes, machine fixes; `compiler/report.klar` renders them with the
  code frame). `tests/selfhost.py` compares the report and `--json` of every checker case (340/340) and runs `fix` in
  three modes on each of them (747/747 identical outputs and files). `klarc build` prints the `built ...` line and
  `klarc run` shows warnings, like `klar`.
- `klarc new`, `outline`, `refs`, `rename`, `doc`, `spec`, `ast` (compiler/inspect.klar, astjson.klar): the same
  output and files as the Python commands, checked by `tests/selfhost.py` on every file of the repository and every
  checker case. New built-in `make_dir(path)` (creates missing parents; effect `fs`).
- `klarc patch` (compiler/patch.klar): the AI patch protocol in Klar — the same reports, diffs and written files as
  `klar patch` (`tests/selfhost.py` compares hundreds of patches on the repository's files); with `--test` the tests
  are not run yet. The Klar loader can take file texts instead of reading them (`load_program_with`).
- `run_capture(args, dir, input)` (effect `proc`): runs a program in a directory and returns `[exit code, stdout, stderr]`;
  both pipes are read together (poll), so a chatty program cannot block. Linux x86-64 and arm64 (new intrinsics
  `os_dup2`, `os_chdir`, `os_execve`, `os_poll`) and the interpreter; Windows returns an error for now.
- `klarc dev [--json] [--no-run] [--stdin TEXT]` (compiler/dev.klar): one AI-loop step without Python — check,
  native tests, native run, the same compact report as `klar dev` (runtime errors are read back from the text the
  runtime prints). Properties are reported as `skipped`.
- `klarc add`, `remove`, `fetch`, `update`, `deps` (compiler/pkg.klar): the package commands without Python, with
  the same output, `klar.toml` edits and `klar.lock`; `tests/selfhost.py` replays a scenario with path and git
  dependencies on both. New built-ins `remove_file(path)` and `current_dir()` (effect `fs`; Linux unlink /
  getcwd, Windows DeleteFileA / GetCurrentDirectoryA); klarc's tools no longer trust `$PWD` for absolute paths.
- `klarc eval [STATEMENTS...] EXPR [--in FILE] [--json]` (compiler/evaluate.klar): the type from the Klar checker,
  the value from a native run of the expression as a test block; the same output as `klar eval`.
- `build.sh` / `build.bat`: build klarc without Python from a seed compiler (`seed/klarc-<target>`, `$KLARC`, or the
  release download), with the self-reproduction check; `.github/workflows/release.yml` builds the seeds for Linux
  x86-64, Linux arm64 and Windows, checks that they reproduce themselves and attaches them to a release.
- `klarc view [-o OUT] [--json] [--run]` (compiler/view.klar): the same page and data as `klar view` (checked on
  every example, native test, benchmark, std and compiler file); `--run` runs the program natively and shows its
  output and error (call counts and times stay with `klar view --run`).
- `klarc lsp` (compiler/lsp.klar): the language server without Python — the same responses as `klar lsp` to every
  request (`tests/selfhost.py` replays sessions of hover, definition, references, rename, completion, signature help,
  symbols, formatting and code actions on the examples, native tests and compiler files and compares every
  message). The checker now records the types of `let` and pattern bindings; new built-in `read_exact(n)` (n bytes
  of standard input). The VS Code extension runs it when `klar.klarcPath` is set.
- `klarc repl [--plain]` (compiler/repl.klar): the interactive session without Python — the same checks, messages,
  values and commands as `klar repl` (`tests/selfhost.py` compares a transcript); each input runs natively, with
  the earlier statements replayed and their output hidden.
- `klarc coverage [--main] [--runs N] [--min P] [--json]` (compiler/coverage.klar): the same report as
  `klar coverage`, from native runs: in a coverage build (`lower_program_cov`) each statement of the file reports
  its line the first time it runs (`klar/rt/cov.klar`, unbuffered on stderr, so forked property runs count too).
- `klarc profile [args] [--json] [--top N]` (compiler/profile.klar): the report of `klar profile` from a native
  profile build (`lower_program_mode`, klar/rt/profile.klar): calls, total and self time per user function, the hot
  lines. Call counts and line counts equal the interpreter's; times are those of the machine code, and built-in
  functions (machine code too) are not listed. With this every `klar` command has a `klarc` counterpart.
- `klarc test` reports like `klar test`: each failure with its runtime error and the test's output, `-k`/`--filter`,
  `-q`, `--runs`, `--seed`, warnings first.
- Property tests in native code: test executables run `property` blocks too (`exe RUNS SEED INDEX`). The runtime
  (`klar/rt/prop.klar`) reproduces the interpreter's generator exactly — CPython's `random.Random(f"{seed}:{name}")`
  (SHA-512 seeding, Mersenne Twister, randbelow, uniform, `round(x, 3)`) — so the native report names the same
  counterexample after the same number of runs; each run is a child process (fork), the failure comes back through a
  pipe and the inputs are shrunk like in the interpreter. Both lowerings emit it identically (`tests/selfhost.py`),
  and `tests/native_diff.py` compares the reports of `tests/native/properties.klar` character for character.
  Where there is no fork (Windows) each run happens in the test process: `os_setjmp` / `os_longjmp` (new intrinsics,
  x86-64) bring a failure back to the runner; `tests/native_diff.py --windows` checks the reports under wine.
- macOS (experimental): `klar build --target macos` / `klarc build --target macos` write a static x86-64 Mach-O
  executable (LC_UNIXTHREAD, no dyld, BSD system calls; `klar/native/link.py` and `compiler/link.klar`, byte for
  byte the same). Untested on a real Mac: `tests/macho_run.py` runs such executables on Linux in the Unicorn CPU
  emulator with the macOS system calls done by Python, `tests/native_diff.py --macos` checks every native test with
  it, and `tests/bootstrap.py` checks that the macOS build of klarc builds programs byte for byte like klarc on Linux.
  `par_map` uses worker processes there too (sysctl hw.ncpu). `klar run` on a Mac still uses the Python backend.
- `docs/SPEC.md` is the Klar 1.0 specification, with the stability rules for 1.x; `docs/SPEC.en.md` is its English
  translation.
- Tests for every 1.0 addition: the Mach-O format and a run under the emulator, property runs without fork (Windows,
  under wine), `build.sh` building klarc from a seed, `klar profile` (exit, lambda names, check errors), the new
  checker rules (also as `tests/selfhost_cases.txt` cases for klarc), and a check that `klar explain` knows every
  diagnostic code the compilers and the runtime use.

### Fixed
- The effects of `par_map`'s lambda could escape through function values: calling (or passing on) a captured function
  or a parameter that holds one is now E0406 (the native run had silently lost the effects).
- `==` on values that contain functions (`Some(f)`, records with function fields) is E0211, like `f == g`.
- A property input of a newtype with `requires` is E0605: random values would break its invariant.
- A path that ends in `exit(...)` counts as finished, like `fail(...)` (no more E0205 after it).
- W0104 on a non-ASCII name suggested renaming it to itself; it now says names use ASCII letters, digits and `_`.
- `klar explain R0013` (exit() in a test) was missing; Python's lexer read other scripts' digits (`٣`) as numbers
  and crashed on `²` (only `0`-`9` now, like klarc).
- `klarc profile`: lambdas are named after the line of the call that runs them (like `klar profile`), `par_map`
  runs in-process under profiling (forked workers lost their counts), check errors use `klar`'s JSON, and `exit(n)`
  ends a profiled program normally with its status in both profilers.
- `klar ast` crashed on functions with trait bounds (a dict of spans was not converted to JSON).
- Native test executables reported every test's call stack at the place of the first test.
- `klarc run`/`build` showed the runtime's own warnings (the runtime reports as `rt`).
- Native error reports showed strings in `note: values:` without quotes (`s = x`); they are quoted like in the
  interpreter (`s = "x"`).

### Changed
- Map keys may be any values without functions (`Map[Point, Int]`, `Map[Float, Str]`): only the literal `Map { ... }`
  had rejected them, while `set` and annotations accepted them and both backends handle them.
- `sin`, `cos`, `ln`, `exp` and `**` on floats use a software implementation (`klar/rt/softmath.klar`, fdlibm
  algorithms with an exact reduction of huge arguments) on every target instead of x87 instructions: results are the
  same on x86-64 and arm64 and closer to correctly rounded.

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
