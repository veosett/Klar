"""Command line interface: klar run|check|test|profile|ast|spec|explain."""
import argparse
import io
import re
import subprocess
import json
import os
import sys

from . import __version__
from .diagnostics import Diagnostic, Span, explain
from .errors import KlarExit, KlarRuntimeError
from .interpreter import Interpreter, Profiler, run_with_big_stack
from .loader import load_path
from .codegen import CompiledProgram, Unsupported
from .nodes import to_json, FnDecl, PropertyDecl

HERE = os.path.dirname(os.path.abspath(__file__))


def emit_json(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def print_diags(loaded, diags, stream=None):
    stream = stream or sys.stderr       # (looked up at the call: `klar mcp` captures it)
    for d in diags:
        print(d.format(loaded.sources.get(d.span.file)), file=stream)
        print(file=stream)
    errs = sum(1 for d in diags if d.severity == "error")
    warns = sum(1 for d in diags if d.severity == "warning")
    if diags:
        print(f"{errs} error(s), {warns} warning(s)", file=stream)


def user_diags(loaded):
    # the prelude is never reported; the native runtime (rt/*.klar) only when it has errors
    return [d for d in loaded.diags if d.span.file != "prelude.klar" and
            not (d.span.file.startswith("rt/") and d.severity != "error")]


def runtime_guard(fn, interp):
    try:
        return run_with_big_stack(fn), None
    except KlarRuntimeError as ex:
        return None, ex
    except RecursionError:
        span = interp.stack[-1][1] if interp.stack else Span("?", 0, 0, 0, 0)
        return None, KlarRuntimeError("R0006", "stack overflow (recursion too deep)", span,
                                      hint="check the base case of the recursion")


def fail_check(args, loaded):
    diags = user_diags(loaded)
    if args.json:
        emit_json({"ok": False, "stage": "check", "diagnostics": [d.to_dict() for d in diags]})
    else:
        print_diags(loaded, diags)
    return 1


def has_main(loaded):
    return any(isinstance(d, FnDecl) and d.name == "main" for d in loaded.program.decls)


def cmd_check(args):
    loaded = load_path(args.file)
    diags = user_diags(loaded)
    if args.json:
        emit_json({"ok": not loaded.has_errors(), "diagnostics": [d.to_dict() for d in diags]})
    else:
        print_diags(loaded, diags, sys.stdout)
        if not diags:
            print("ok: no problems found")
    return 1 if loaded.has_errors() else 0


def prepare_run(args):
    loaded = load_path(args.file)
    if loaded.has_errors() or loaded.program is None:
        return loaded, fail_check(args, loaded)
    if not has_main(loaded):
        d = Diagnostic("E0501", "error", "no `fn main()` to run", Span(os.path.basename(args.file), 1, 1, 1, 1),
                       hint="add `fn main() uses io { print(\"hello\") }`, or use `klar test` to run tests")
        if args.json:
            emit_json({"ok": False, "stage": "check", "diagnostics": [d.to_dict()]})
        else:
            print_diags(loaded, [d])
        return loaded, 1
    return loaded, None


RUNTIME_ERROR = re.compile(r"runtime error\[(\w+)\]: (.*)\n  --> (.+?):(\d+):(\d+)")


def run_native(args, loaded):
    """Build (cached) and run a native executable. Returns exit code, or None if unsupported."""
    from .native.build import cached_build, host_target
    from .native.lower import NativeUnsupported
    if host_target() is None:
        return None
    try:
        sb = getattr(args, "sandbox", None)
        exe = cached_build(args.file, loaded, allow=sb.rights if sb else None)
    except NativeUnsupported as why:
        if args.verbose:
            print(f"note: native backend cannot compile this program yet ({why}); using the Python backend",
                  file=sys.stderr)
        return None
    if args.verbose and not args.json:
        print(f"note: backend = native ({exe})", file=sys.stderr)
    if not args.json:
        sys.stdout.flush()
        try:
            sys.stdout.fileno()
            sys.stderr.fileno()
            return subprocess.run([exe, *args.args]).returncode
        except (AttributeError, OSError, io.UnsupportedOperation):
            p = subprocess.run([exe, *args.args], capture_output=True, text=True)
            sys.stdout.write(p.stdout)
            sys.stderr.write(p.stderr)
            return p.returncode
    p = subprocess.run([exe, *args.args], capture_output=True, text=True)
    res = {"ok": p.returncode == 0, "stage": "run", "backend": "native", "stdout": p.stdout, "stderr": p.stderr,
           "diagnostics": [d.to_dict() for d in user_diags(loaded) if d.severity == "warning"]}
    m = RUNTIME_ERROR.search(p.stderr)
    if m:
        res["runtime_error"] = {"code": m.group(1), "message": m.group(2),
                                "span": {"file": m.group(3), "line": int(m.group(4)), "col": int(m.group(5))},
                                "text": p.stderr[m.start():]}
        res["stderr"] = p.stderr[:m.start()]
    emit_json(res)
    return p.returncode


def cmd_build(args):
    from .native.build import build, host_target
    from .native.lower import NativeUnsupported
    sandbox = sandbox_of(args)
    if sandbox is False:
        return 2
    loaded = load_path(args.file, with_runtime=True)
    if loaded.has_errors():
        return fail_check(args, loaded)
    target = args.target or host_target() or "linux"
    try:
        out, _ = build(args.file, out=args.output, target=target, loaded=loaded,
                       allow=sandbox.rights if sandbox else None)
    except NativeUnsupported as why:
        print(f"error: the native backend cannot compile this program yet: {why}", file=sys.stderr)
        return 1
    size = os.path.getsize(out)
    if not getattr(args, "quiet", False):
        print(f"built {out} ({target}, {size // 1024} KB, no runtime dependencies)")
    return 0


def sandbox_of(args):
    """The rights of `--allow` (None without it); prints the problem and returns False for an unknown right."""
    from .sandbox import RightsError, Sandbox
    if getattr(args, "allow", None) is None:
        return None
    try:
        return Sandbox(args.allow)
    except RightsError as ex:
        print(f"error: {ex}", file=sys.stderr)
        return False


def cmd_run(args):
    sandbox = sandbox_of(args)
    if sandbox is False:
        return 2
    args.sandbox = sandbox
    loaded, code = prepare_run(args)
    if code is not None:
        return code
    if not args.interp and not args.py and not args.emit_python:
        warnings = [d for d in user_diags(loaded) if d.severity == "warning"]
        if warnings and not args.json and not args.quiet:
            print_diags(loaded, warnings)
        rc = run_native(args, loaded)
        if rc is not None:
            return rc
    if args.emit_python:
        try:
            print(CompiledProgram(loaded).src)
            return 0
        except Unsupported as why:
            print(f"cannot compile: {why}", file=sys.stderr)
            return 1
    warnings = [d for d in user_diags(loaded) if d.severity == "warning"]
    if warnings and not args.json and not args.quiet and (args.interp or args.py):
        print_diags(loaded, warnings)
    out = io.StringIO() if args.json else sys.stdout
    errs = io.StringIO() if args.json else sys.stderr
    interp = Interpreter(loaded, out=out, err_stream=errs, cli_args=args.args)
    interp.sandbox = sandbox
    runner = interp
    backend = "interpreter"
    if not args.interp:
        try:
            runner = CompiledProgram(loaded, out=out, err_stream=errs, cli_args=args.args)
            runner.ctx.sandbox = sandbox
            backend = "compiled"
        except Unsupported as why:
            if args.verbose:
                print(f"note: using the interpreter ({why})", file=sys.stderr)
    if args.verbose and not args.json:
        print(f"note: backend = {backend}", file=sys.stderr)
    _, err = runtime_guard(runner.run_main, interp)
    exit_code = None
    if isinstance(err, KlarExit):
        exit_code, err = err.exit_code, None
    if args.json:
        res = {"ok": err is None, **({"exit_code": exit_code} if exit_code is not None else {}), "stage": "run", "backend": backend, "stdout": out.getvalue(), "stderr": errs.getvalue(),
               "diagnostics": [d.to_dict() for d in warnings]}
        if err:
            res["runtime_error"] = err.to_dict()
        emit_json(res)
    elif err:
        sys.stdout.flush()
        print(err.to_diag().format(loaded.sources.get(err.span.file)), file=sys.stderr)
    if exit_code is not None:
        sys.stdout.flush()
        return exit_code
    return 1 if err else 0


def cmd_test(args):
    from .contracts import load_with_contracts
    loaded, full = load_with_contracts(args.file)
    if loaded.has_errors() or loaded.program is None:
        return fail_check(args, loaded)
    interp = Interpreter(full, err_stream=io.StringIO())
    results = []
    for t in interp.tests:
        if args.filter and args.filter not in t.name:
            continue
        buf = io.StringIO()
        interp.out = buf
        interp.err = buf
        _, err = runtime_guard(lambda: interp.run_test(t, runs=args.runs, seed=args.seed), interp)
        kind = "property" if isinstance(t, PropertyDecl) else ("doc" if t.name.startswith("doc: ") else "test")
        results.append((t, kind, err, buf.getvalue()))
    passed = sum(1 for r in results if r[2] is None)
    failed = len(results) - passed
    if args.json:
        emit_json({
            "ok": failed == 0, "stage": "test", "passed": passed, "failed": failed,
            "tests": [{"name": t.name, "kind": k, "status": "passed" if e is None else "failed",
                       "line": t.span.line, "output": o,
                       **({"error": e.to_dict()} if e else {})} for t, k, e, o in results],
            "diagnostics": [d.to_dict() for d in user_diags(loaded)]})
    else:
        warnings = [d for d in user_diags(loaded) if d.severity == "warning"]
        if warnings and not args.quiet:
            print_diags(loaded, warnings)
        for t, kind, e, o in results:
            label = {"test": "", "doc": "", "property": f" [property x{args.runs}]"}[kind]
            if e is None:
                print(f"  PASS  {t.name}{label}")
            else:
                print(f"  FAIL  {t.name}{label}")
                for line in e.to_diag().format(full.sources.get(e.span.file)).split("\n"):
                    print("        " + line)
                if o:
                    print("        output:")
                    for line in o.rstrip("\n").split("\n"):
                        print("          " + line)
        if not results:
            print("no tests found")
        print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


def cmd_profile(args):
    loaded, code = prepare_run(args)
    if code is not None:
        return code
    out = io.StringIO() if (args.json or not args.show_output) else sys.stdout
    interp = Interpreter(loaded, out=out, err_stream=io.StringIO(), cli_args=args.args)
    interp.prof = prof = Profiler()
    _, err = runtime_guard(interp.run_main, interp)
    prof.finish()
    exit_code = 0
    if isinstance(err, KlarExit):  # exit(n) ends the program normally: its exit status is the profile's
        exit_code, err = err.exit_code, None
    total = prof.total()
    funcs = sorted(prof.funcs.items(), key=lambda kv: -kv[1][2])
    lines = sorted(prof.lines.items(), key=lambda kv: -kv[1])[:args.top]
    if args.json:
        emit_json({
            "ok": err is None, "total_ms": round(total * 1000, 3),
            "functions": [{"function": k, "calls": c, "total_ms": round(t * 1000, 3), "self_ms": round(s * 1000, 3),
                           "self_percent": round(100 * s / total, 2) if total else 0} for k, (c, t, s) in funcs],
            "hot_lines": [{"file": f, "line": ln, "executions": n,
                           "code": (loaded.sources.get(f, "").split("\n")[ln - 1].strip()
                                    if f in loaded.sources else "")} for (f, ln), n in lines],
            **({"runtime_error": err.to_dict()} if err else {})})
        return 1 if err else exit_code
    print(f"Klar profile: {args.file} — total {total * 1000:.1f} ms "
          f"(profiling adds overhead; compare functions relative to each other)\n")
    print(f"{'self %':>7} {'self ms':>10} {'total ms':>10} {'calls':>9}  function")
    print("-" * 72)
    for key, (calls, tot, slf) in funcs[:args.top]:
        pct = 100 * slf / total if total else 0
        print(f"{pct:6.1f}% {slf * 1000:10.2f} {tot * 1000:10.2f} {calls:9d}  {key}")
    print("\nHot lines (statements executed):")
    print(f"{'count':>10}  location        code")
    for (f, ln), n in lines:
        code = loaded.sources.get(f, "").split("\n")[ln - 1].strip() if f in loaded.sources else ""
        print(f"{n:10d}  {f + ':' + str(ln):<15} {code[:60]}")
    if err:
        print()
        print(err.to_diag().format(loaded.sources.get(err.span.file)), file=sys.stderr)
    return 1 if err else exit_code


# ---------------------------------------------------------------------------
# klar fix: apply machine-applicable fixes until nothing changes
# ---------------------------------------------------------------------------
def offset_of(text, line, col):
    lines = text.split("\n")
    return sum(len(l) + 1 for l in lines[:line - 1]) + col - 1


def apply_edits(text, edits):
    """Apply non-overlapping edits (spans are 1-based, end exclusive); later edits first."""
    ranges = []
    for e in edits:
        sp = e["span"]
        ranges.append((offset_of(text, sp.line, sp.col), offset_of(text, sp.end_line, sp.end_col), e["text"]))
    ranges.sort(key=lambda r: (r[0], r[1]), reverse=True)
    last_start = None
    for start, end, new in ranges:
        if last_start is not None and end > last_start:
            continue  # overlapping: retry on the next round
        text = text[:start] + new + text[end:]
        last_start = start
    return text


def cmd_fix(args):
    from .diagnostics import fix_edits
    root_dir = os.path.dirname(os.path.abspath(args.file))
    applied = []
    for _round in range(50):
        loaded = load_path(args.file)
        per_file = {}
        for d in user_diags(loaded):
            if not d.fix or (d.severity != "error" and not args.warnings):
                continue
            if not d.fix.get("safe", True) and not args.all:
                continue
            for e in fix_edits(d.fix):   # an edit may target another module (e.g. adding `pub` there)
                fname = e["span"].file or d.span.file
                if fname.startswith("std/") or fname.startswith("rt/") or fname == "prelude.klar":
                    continue
                per_file.setdefault(fname, []).append((d, e))
        if not per_file:
            break
        changed = False
        for fname, pairs in per_file.items():
            path = os.path.join(root_dir, *fname.split("/"))
            with open(path, encoding="utf-8") as f:
                text = f.read()
            new = apply_edits(text, [e for _, e in pairs])
            if new != text:
                changed = True
                seen = []
                for d, _ in pairs:
                    if d not in seen:
                        seen.append(d)
                applied += [{"code": d.code, "at": d.span.short(), "message": d.message} for d in seen]
                if not args.dry_run:
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(new)
        if not changed or args.dry_run:
            break
    loaded = load_path(args.file)
    remaining = user_diags(loaded)
    if args.json:
        emit_json({"ok": not loaded.has_errors(), "applied": applied,
                   "remaining": [compact(d) for d in remaining]})
    else:
        for a in applied:
            print(f"fixed  {a['code']}  {a['at']}  {a['message']}")
        if not applied:
            print("nothing to fix automatically")
        if remaining:
            print()
            print_diags(loaded, remaining, sys.stdout)
        else:
            print("ok: no problems left")
    return 1 if loaded.has_errors() else 0


# ---------------------------------------------------------------------------
# klar dev: the whole AI loop step in one call (check + test + run), compact output
# ---------------------------------------------------------------------------
def compact(d):
    from .diagnostics import fix_edits
    out = {"code": d.code, "msg": d.message, "at": d.span.short()}
    if d.hint:
        out["hint"] = d.hint
    if d.fix:
        out["fix"] = [{"at": f"{e['span'].line}:{e['span'].col}-{e['span'].end_line}:{e['span'].end_col}",
                       "text": e["text"]} for e in fix_edits(d.fix)]
        out["auto"] = bool(d.fix.get("safe", True))
    return out


def compact_rt(e):
    out = {"code": e.code, "msg": e.message, "at": e.span.short()}
    if e.details:
        out["values"] = e.details
    if e.stack:
        out["stack"] = [f"{n}@{sp.short()}" for n, sp in reversed(e.stack)][:6]
    if e.hint:
        out["hint"] = e.hint
    return out


def cmd_dev(args):
    from .contracts import load_with_contracts
    loaded, full = load_with_contracts(args.file)
    diags = user_diags(loaded)
    errors = [d for d in diags if d.severity == "error"]
    warnings = [d for d in diags if d.severity == "warning"]
    report = {"ok": False, "errors": [compact(d) for d in errors],
              "warnings": [compact(d) for d in warnings][:args.max_warnings]}
    if errors:
        auto = sum(1 for d in errors if d.fix and d.fix.get("safe", True))
        report["next"] = (f"fix {len(errors)} error(s)" + (f"; {auto} can be fixed by `klar fix`" if auto else ""))
        return dev_out(args, report, loaded)
    interp = Interpreter(full, err_stream=io.StringIO())
    failed, passed = [], 0
    for t in interp.tests:
        buf = io.StringIO()
        interp.out = buf
        interp.err = buf
        _, err = runtime_guard(lambda: interp.run_test(t, runs=args.runs, seed=0), interp)
        if err is None:
            passed += 1
        else:
            failed.append({"name": t.name, **compact_rt(err)})
    report["tests"] = {"passed": passed, "failed": failed}
    run_err = None
    if has_main(loaded) and not args.no_run:
        out, errs = io.StringIO(), io.StringIO()
        interp2 = Interpreter(loaded, out=out, err_stream=errs, inp=io.StringIO(args.stdin or ""))
        try:
            runner = CompiledProgram(loaded, out=out, err_stream=errs, inp=io.StringIO(args.stdin or ""))
        except Unsupported:
            runner = interp2
        _, run_err = runtime_guard(runner.run_main, interp2)
        exit_code = None
        if isinstance(run_err, KlarExit):
            exit_code, run_err = run_err.exit_code, None
        text = out.getvalue()
        report["run"] = {"ok": run_err is None, **({"exit_code": exit_code} if exit_code is not None else {}),
                         "stdout": text if len(text) <= args.max_output else text[:args.max_output] + "…(truncated)"}
        if errs.getvalue():
            report["run"]["stderr"] = errs.getvalue()[:args.max_output]
        if run_err:
            report["run"]["error"] = compact_rt(run_err)
    report["ok"] = not failed and run_err is None
    if failed:
        report["next"] = f"fix {len(failed)} failing test(s)"
    elif run_err:
        report["next"] = "fix the runtime error"
    elif not interp.tests:
        report["next"] = "add tests (`test`, `/// >>>` doc-tests or `property`)"
    else:
        report["next"] = "done"
    return dev_out(args, report, loaded)


def dev_out(args, report, loaded):
    if args.json:
        print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    else:
        for d in report["errors"]:
            print(f"error {d['code']} {d['at']}: {d['msg']}" + (f"  [hint: {d['hint']}]" if d.get("hint") else ""))
        for d in report["warnings"]:
            print(f"warn  {d['code']} {d['at']}: {d['msg']}")
        if "tests" in report:
            t = report["tests"]
            print(f"tests: {t['passed']} passed, {len(t['failed'])} failed")
            for f in t["failed"]:
                print(f"  FAIL {f['name']}: {f['code']} {f['at']} {f['msg']} {' '.join(f.get('values', []))}")
        if "run" in report:
            r = report["run"]
            print("run: " + ("ok" if r["ok"] else f"ERROR {r['error']['code']} {r['error']['at']} {r['error']['msg']}"))
            if r["stdout"]:
                print("stdout:\n" + r["stdout"].rstrip("\n"))
        print(f"next: {report['next']}")
    return 0 if report["ok"] else 1


def cmd_ast(args):
    loaded = load_path(args.file)
    if loaded.program is None:
        emit_json({"ok": False, "diagnostics": [d.to_dict() for d in user_diags(loaded)]})
        return 1
    from .nodes import number
    number(loaded.program)
    print(json.dumps(to_json(loaded.program), ensure_ascii=False, indent=1 if args.pretty else None))
    return 0


def stdlib_reference():
    """Generated from the real signatures, so it can never drift from the implementation."""
    from .builtins import GLOBALS, METHODS
    lines = ["## Standard library (generated from signatures)", "",
             "Prelude (always available): `type Pair[A, B] { first, second }`, `type Entry[K, V] { key, value }`, "
             "`type Indexed[T] { index, value }`, `const PI: Float`, `const E: Float`.", "",
             "Std modules (import explicitly, e.g. `use std.math.{gcd}`): see `klar/std/*.klar`.", "",
             "Global functions:"]
    for name, (sig, _) in GLOBALS.items():
        lines.append(f"- `{sig}`")
    lines.append("")
    lines.append("Methods (call as `value.method(args)`; `self` is the receiver). Every value has `.to_str()`.")
    for owner, ms in METHODS.items():
        lines.append(f"\n{owner}:")
        for name, (sig, _) in ms.items():
            lines.append(f"- `{sig.replace('fn ', '', 1)}`")
    return "\n".join(lines)


def std_modules_reference():
    std_dir = os.path.join(HERE, "std")
    if not os.path.isdir(std_dir):
        return ""
    from .parser import parse
    out = ["", "## Std modules"]
    for fname in sorted(os.listdir(std_dir)):
        if not fname.endswith(".klar"):
            continue
        with open(os.path.join(std_dir, fname), encoding="utf-8") as f:
            src = f.read()
        prog = parse(src, fname)
        out.append(f"\n`use std.{fname[:-5]}.{{...}}`:")
        for d in prog.decls:
            if isinstance(d, FnDecl):
                ps = ", ".join(f"{p.name}: {src_text(src, p.type.span)}" for p in d.params)
                ret = f" -> {src_text(src, d.ret.span)}" if d.ret else ""
                tps = f"[{', '.join(d.type_params)}]" if d.type_params else ""
                doc = f" — {d.doc.splitlines()[0]}" if d.doc else ""
                out.append(f"- `{d.name}{tps}({ps}){ret}`{doc}")
    return "\n".join(out)


def src_text(src, span):
    line = src.split("\n")[span.line - 1]
    return line[span.col - 1:span.end_col - 1] if span.line == span.end_line else line[span.col - 1:]


def cmd_spec(args):
    with open(os.path.join(HERE, "ai_reference.md"), encoding="utf-8") as f:
        print(f.read())
    print(stdlib_reference())
    print(std_modules_reference())
    return 0


def cmd_explain(args):
    print(explain(args.code))
    return 0


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(prog="klar", description=f"Klar {__version__} — a language designed for AI authors")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run", help="check and run fn main()")
    p.add_argument("file")
    p.add_argument("args", nargs="*", help="arguments for cli_args() (put them after --)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("-q", "--quiet", action="store_true", help="hide warnings")
    p.add_argument("--interp", action="store_true", help="use the tree-walking reference interpreter")
    p.add_argument("--py", action="store_true", help="use the Klar -> Python backend instead of native code")
    p.add_argument("-v", "--verbose", action="store_true", help="report which backend runs the program")
    p.add_argument("--emit-python", action="store_true", help="print the generated Python code and exit")
    p.add_argument("--allow", metavar="RIGHTS", help="run with only these rights, e.g. fs:./data,proc:git,time "
                                                     "(io is always allowed; anything else is R0016)")
    p.set_defaults(fn=cmd_run)
    p = sub.add_parser("build", help="compile to a standalone native executable (Linux ELF, Windows PE, macOS Mach-O)")
    p.add_argument("file")
    p.add_argument("-o", "--output", help="output path (default: next to the source)")
    p.add_argument("--target", choices=["linux", "windows", "linux-arm64", "macos"],
                   help="default: this machine (macos: x86-64, experimental)")
    p.add_argument("--json", action="store_true")
    p.add_argument("-q", "--quiet", action="store_true", help="print nothing on success")
    p.add_argument("--allow", metavar="RIGHTS", help="build the rights into the executable, e.g. fs:./data,time "
                                                     "(io is always allowed; anything else is R0016)")
    p.set_defaults(fn=cmd_build)
    p = sub.add_parser("check", help="type-check without running")
    p.add_argument("file")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_check)
    p = sub.add_parser("test", help="run test, doc-test and property blocks")
    p.add_argument("file")
    p.add_argument("--json", action="store_true")
    p.add_argument("-q", "--quiet", action="store_true")
    p.add_argument("-k", "--filter", help="only tests whose name contains this text")
    p.add_argument("--runs", type=int, default=100, help="inputs per property (default 100)")
    p.add_argument("--seed", type=int, default=0, help="random seed for properties (default 0)")
    p.set_defaults(fn=cmd_test)
    p = sub.add_parser("profile", help="run main() and report time per function and hot lines")
    p.add_argument("file")
    p.add_argument("args", nargs="*")
    p.add_argument("--json", action="store_true")
    p.add_argument("--top", type=int, default=15, help="rows to show (default 15)")
    p.add_argument("--show-output", action="store_true", help="also print the program's output")
    p.set_defaults(fn=cmd_profile)
    p = sub.add_parser("dev", help="one AI-loop step: check + tests + run, compact report (use --json)")
    p.add_argument("file")
    p.add_argument("--json", action="store_true", help="single-line compact JSON (fewest tokens)")
    p.add_argument("--runs", type=int, default=50, help="inputs per property (default 50)")
    p.add_argument("--no-run", action="store_true", help="do not run main()")
    p.add_argument("--stdin", help="text passed to read_line()")
    p.add_argument("--max-output", type=int, default=2000)
    p.add_argument("--max-warnings", type=int, default=10)
    p.set_defaults(fn=cmd_dev)
    p = sub.add_parser("fix", help="apply safe machine fixes from diagnostics (repeatedly)")
    p.add_argument("file")
    p.add_argument("--json", action="store_true")
    p.add_argument("--dry-run", action="store_true", help="show what would change, write nothing")
    p.add_argument("--all", action="store_true", help="also apply guesses (\"did you mean\")")
    p.add_argument("--warnings", action="store_true", help="also fix warnings")
    p.set_defaults(fn=cmd_fix)
    p = sub.add_parser("ast", help="dump the AST as JSON")
    p.add_argument("file")
    p.add_argument("--pretty", action="store_true")
    p.set_defaults(fn=cmd_ast)
    p = sub.add_parser("spec", help="print the compact language reference (paste it into an AI prompt)")
    p.set_defaults(fn=cmd_spec)
    p = sub.add_parser("explain", help="explain an error code, e.g. E0202")
    p.add_argument("code")
    p.set_defaults(fn=cmd_explain)
    from .tools.commands import register
    register(sub)
    args = ap.parse_args(argv)
    return args.fn(args)
