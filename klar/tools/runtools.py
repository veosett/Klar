"""`klar eval`, `klar coverage`, `klar new`.

eval      evaluate an expression (optionally in the context of a file) and print `value : Type`;
          the fastest way for an AI to check how a built-in behaves without writing a program.
coverage  run the tests (and optionally main) and list the statements that were never executed;
          tells an AI which code its tests do not exercise yet.
new       create a project skeleton with a test, a doc-test and an AGENTS.md for AI assistants.
"""
import io
import os
import re

from .. import nodes as N
from ..errors import KlarRuntimeError
from ..interpreter import Interpreter, Profiler, run_with_big_stack
from ..loader import load_path, load_source
from ..safety import iter_nodes
from ..types import prune, show

ENTRY = "klar_eval_entry"
VALUE = "klar_eval_value"


# ---- eval ------------------------------------------------------------------------------------------------
def evaluate(parts, context_file=None):
    """Returns a dict: {ok, value, type, output} or {ok: False, diagnostics | error}."""
    *stmts, expr = parts
    base, root, fname = "", None, "eval.klar"
    if context_file:
        with open(context_file, encoding="utf-8") as f:
            base = f.read()
        root = os.path.dirname(os.path.abspath(context_file))
        fname = os.path.basename(context_file)
    header = (base.rstrip("\n") + "\n\n") if base else ""
    offset = header.count("\n") + 1          # input line k is source line offset + k
    body = "".join("  " + s + "\n" for s in stmts)
    src = header + f"fn {ENTRY}() uses io, time, rand, fs {{\n{body}  let {VALUE} = {expr}\n  let _ = dbg({VALUE})\n}}\n"
    loaded = load_source(src, fname, root=root)
    errors = [d for d in loaded.diags if d.severity == "error" and d.span.file == fname]
    if errors:
        return {"ok": False, "diagnostics": [
            {"code": d.code, "message": d.message, "hint": d.hint,
             "line": d.span.line - offset if d.span.line > offset else d.span.line,
             "where": "input" if d.span.line > offset else fname} for d in errors]}
    entry = next(d for d in loaded.program.decls if isinstance(d, N.FnDecl) and d.name == ENTRY)
    let = next(n for n in iter_nodes(entry) if isinstance(n, N.Let) and n.name == VALUE)
    typ = show(prune(let.value.kt)) if getattr(let.value, "kt", None) is not None else "?"
    out, err = io.StringIO(), io.StringIO()
    interp = Interpreter(loaded, out=out, err_stream=err)
    try:
        def go():
            interp.initialize()
            fv = interp.main_env.vars[ENTRY]
            interp.call_value(fv, [], entry.name_span)
        run_with_big_stack(go)
    except KlarRuntimeError as ex:
        return {"ok": False, "error": {"code": ex.code, "message": ex.message}, "output": out.getvalue()}
    value = None
    for line in err.getvalue().splitlines():
        m = re.match(rf"\[dbg [^\]]*\] {VALUE} = (.*)$", line)
        if m:
            value = m.group(1)
    return {"ok": True, "value": value, "type": typ, "output": out.getvalue()}


# ---- coverage ----------------------------------------------------------------------------------------------
def statement_lines(fn):
    lines = set()
    for n in iter_nodes(fn.body if hasattr(fn, "body") else fn):
        if isinstance(n, N.Block):
            for s in n.stmts:
                lines.add(s.span.line)
    return lines


def coverage(path, with_main=False, runs=20):
    loaded = load_path(path)
    if loaded.has_errors():
        return {"ok": False, "diagnostics": [d.to_dict() for d in loaded.diags if d.severity == "error"]}
    interp = Interpreter(loaded, out=io.StringIO(), err_stream=io.StringIO())
    interp.prof = prof = Profiler()
    failed = []
    for t in interp.tests:
        try:
            run_with_big_stack(lambda: interp.run_test(t, runs=runs))
        except KlarRuntimeError:
            failed.append(t.name)
        except RecursionError:
            failed.append(t.name)
    has_main = any(isinstance(d, N.FnDecl) and d.name == "main" for d in loaded.program.decls)
    if with_main and has_main:
        try:
            run_with_big_stack(interp.run_main)
        except KlarRuntimeError:
            failed.append("main")
    executed = {ln for (f, ln) in prof.lines if f == loaded.main.display}
    funcs = []
    total = covered = 0
    for d in loaded.program.decls:
        if not isinstance(d, N.FnDecl) or (d.name == "main" and not with_main):
            continue
        lines = statement_lines(d)
        if not lines:
            continue
        miss = sorted(lines - executed)
        total += len(lines)
        covered += len(lines) - len(miss)
        funcs.append({"function": d.name, "line": d.span.line, "statements": len(lines),
                      "covered": len(lines) - len(miss), "missed_lines": miss})
    return {"ok": True, "file": loaded.main.display, "percent": round(100 * covered / total, 1) if total else 100.0,
            "statements": total, "covered": covered, "functions": funcs, "tests_failed": failed,
            "tests_run": len(interp.tests)}


def coverage_text(rep, source):
    if not rep["ok"]:
        return "\n".join(f"error[{d['code']}]: {d['message']}" for d in rep["diagnostics"])
    lines = source.split("\n")
    out = [f"coverage of {rep['file']}: {rep['percent']}% of statements "
           f"({rep['covered']}/{rep['statements']}), {rep['tests_run']} tests"]
    if rep["tests_failed"]:
        out.append(f"failing tests (their remaining statements count as not covered): {', '.join(rep['tests_failed'])}")
    for f in rep["functions"]:
        pct = 100 * f["covered"] // f["statements"]
        mark = "  " if not f["missed_lines"] else "!!"
        out.append(f"{mark} {pct:>3}%  {f['function']} (line {f['line']})")
        for ln in f["missed_lines"][:8]:
            out.append(f"         never run: {ln}: {lines[ln - 1].strip()[:70]}")
        if len(f["missed_lines"]) > 8:
            out.append(f"         ... {len(f['missed_lines']) - 8} more")
    return "\n".join(out)


# ---- new ---------------------------------------------------------------------------------------------------
MAIN_TEMPLATE = '''/// {name}: entry point.
fn main() uses io {{
  print(greeting("world"))
}}

/// Builds a greeting.
/// >>> assert greeting("Klar") == "Hello, Klar!"
fn greeting(who: Str) -> Str {{
  return "Hello, {{who}}!"
}}

test "greeting mentions the name" {{
  assert greeting("AI").contains("AI")
}}
'''

AGENTS_TEMPLATE = '''# Working on {name} (instructions for AI assistants)

This project is written in **Klar**. Get the full language reference (≈2k tokens) with `klar spec`.

## Loop
1. Edit `.klar` files; keep tests next to the code (`test`, doc-tests `/// >>>`, `property`).
2. `klar dev main.klar --json` — check + all tests + run in one step; follow the `next` field.
3. `klar fix main.klar` applies safe fixes; `klar fmt .` normalizes the layout.
4. Look things up instead of guessing: `klar doc split` (built-ins, std, this project), `klar outline main.klar`,
   `klar refs name`, `klar context main.klar name` (one function with its types, tests and callers),
   `klar eval '"a,b".split(",")'`, `klar explain E0701`.
5. Before finishing: `klar coverage main.klar` (untested statements), `klar build main.klar` (native executable).
6. Packages: dependencies are in `klar.toml`; `klar add name --git URL --tag v1` / `--path ../dir`, then
   `use name.{{item}}`; `klar fetch` after cloning, `klar deps` shows the tree.

## Rules that the compiler enforces
No null/exceptions/indexing; handle `Option`/`Result`; values are immutable (`xs = xs.push(x)`);
no shadowing; named arguments for 3+ parameters; `uses io` etc. for effects; Int division needs a
provably non-zero divisor.
'''


LIB_TEMPLATE = '''// {name}: a Klar package. Other projects use it with `klar add {pkg} --git <url>` and `use {pkg}.{{greet}}`;
// its other files are imported as `use {pkg}.<file>.{{...}}`.

/// Says hello.
/// >>> assert greet("Ada") == "Hello, Ada!"
pub fn greet(name: Str) -> Str {{
  return "Hello, {{name}}!"
}}

test "greets" {{
  assert greet("x").starts_with("Hello")
}}
'''


def package_name(name):
    """A snake_case package name from a directory name (`My-App` -> `my_app`)."""
    out = re.sub(r"[^a-z0-9_]", "_", name.lower()).strip("_") or "app"
    return out if out[0].isalpha() else "p_" + out


def new_project(path, lib=False):
    name = os.path.basename(os.path.abspath(path))
    pkg = package_name(name)
    if os.path.exists(path) and os.listdir(path):
        raise FileExistsError(f"{path} exists and is not empty")
    os.makedirs(path, exist_ok=True)
    entry = "lib.klar" if lib else "main.klar"
    run = f"klar test {entry}\n" if lib else "klar run main.klar\nklar test main.klar\nklar build main.klar\n"
    files = {
        "klar.toml": f'[package]\nname = "{pkg}"\nversion = "0.1.0"\n\n[dependencies]\n',
        entry: LIB_TEMPLATE.format(name=name, pkg=pkg) if lib else MAIN_TEMPLATE.format(name=name),
        "AGENTS.md": AGENTS_TEMPLATE.format(name=name).replace("main.klar", entry),
        "README.md": f"# {name}\n\nWritten in [Klar](https://github.com/veosett/Klar).\n\n```sh\n{run}```\n",
        ".gitignore": "build/\n*.exe\n.klar/\n",
    }
    for fname, text in files.items():
        with open(os.path.join(path, fname), "w", encoding="utf-8") as f:
            f.write(text)
    return sorted(files)
