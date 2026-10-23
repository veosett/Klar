# Security

## Reporting

Please report vulnerabilities privately through GitHub (Security → Report a vulnerability) rather than in a public
issue. Include a minimal program or project and the command that shows the problem.

## What Klar guarantees

A program that passes `klar check` cannot, in any backend:

* **break memory safety.** There is no indexing without a check, no null, no pointer arithmetic and no shared mutable
  state. The system intrinsics of the runtime (`peek`, `poke`, `os_*`) exist only in `klar/rt/*.klar`: user code
  cannot name them (E0201), and a module or package cannot pretend to be the runtime. Sizes that would overflow the
  allocator (`"x".repeat(huge)`, `range(0, huge)`) are R0015, values nested deeper than 100 000 levels are R0006
  when printed, compared or hashed, recursion deeper than 10 000 calls is R0006 — never a crash.
* **do effects it does not declare.** Reading files needs `uses fs`, running programs `uses proc`, the network
  `uses net`, and so on (E0401). Tests, doc-tests and properties may use only `io` — so `klar test` cannot touch
  files or run programs. Constants and contracts are pure. Function types carry effects (`fn(Int) -> Unit uses io`), so a
  function without `uses` is pure even when it calls function values, and `par_map` gets only pure functions.
* **race.** The only parallelism is `par_map` with a pure function in worker processes.

## Which commands run code

| command | runs the program's code? | with which effects |
|---|---|---|
| `check`, `fmt`, `outline`, `doc`, `refs`, `ast`, `spec`, `explain`, `deps`, `view` (without `--run`), `lsp` | no | — |
| `test`, `coverage`, `patch` with `"test": true` | the tests | `io` only (the checker enforces it) |
| `run`, `dev`, `eval`, `profile`, `view --run`, `repl`, `coverage --main` | yes | the effects its code declares |
| `fetch`, `add`, `update` | runs `git` | clones the URLs of `klar.toml` |

Treat `run`, `dev`, `eval` and `profile` on an untrusted project like running any other program from it. The
effects a program declares are visible in its signatures (`klar outline`), so a reviewer (or an agent) can see what
it may do before running it. A runtime sandbox that enforces the declared effects is planned (`docs/ROADMAP.md`).

## Tools and untrusted projects

* **Packages.** A value from `klar.toml` or `klar.lock` that starts with `-` (a git URL, tag, branch or revision) is
  refused, so it cannot become a git option; dependency names are `[a-z][a-z0-9_]*`. A `path` dependency may point
  outside the project (as in Cargo): review `klar.toml` before fetching or building an untrusted project.
* **Programs started by a program** (`run_command`, `run_capture`) are looked up in `PATH` only — never in the
  current directory, also on Windows — and get their arguments directly, without a shell.
* **Temporary executables** of `klarc` live in a directory of the user (`~/.klar-cache/klarc`, on Windows the user's
  `%TEMP%`); the Python tool caches builds in `~/.klar-cache`. Nothing is written to a shared `/tmp` under a
  predictable name.
* **`klar view`** escapes all program text and output in the HTML page.
* **The language servers** (`klar lsp`, `klarc lsp`) skip malformed messages instead of stopping.
* **Deeply nested source** (expressions or types nested more than 200 levels) is a diagnostic (E0003) in `klar` and
  `klarc`, not a crash of the tool.
