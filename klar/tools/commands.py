"""CLI front-ends of the developer tools (registered into `klar` by cli.main)."""
import difflib
import json
import os
import sys

from ..loader import load_path


def emit(obj):
    print(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))


def klar_files(paths):
    for p in paths:
        if os.path.isdir(p):
            for root, dirs, files in os.walk(p):
                dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in ("build", "__pycache__", "node_modules"))
                for f in sorted(files):
                    if f.endswith(".klar"):
                        yield os.path.join(root, f)
        else:
            yield p


# ---- fmt -------------------------------------------------------------------------------------------------
def cmd_fmt(args):
    from .fmt import FormatError, format_checked
    changed, failed, report = [], [], []
    for path in klar_files(args.paths or ["."]):
        with open(path, encoding="utf-8") as f:
            src = f.read()
        try:
            new = format_checked(src)
        except FormatError as ex:
            failed.append(path)
            report.append({"file": path, "error": str(ex)})
            if not args.json:
                print(f"{path}: {ex}", file=sys.stderr)
            continue
        if new != src:
            changed.append(path)
            report.append({"file": path, "changed": True})
            if args.diff:
                sys.stdout.writelines(difflib.unified_diff(src.splitlines(True), new.splitlines(True),
                                                           path, path + " (formatted)"))
            if not args.check and not args.diff:
                with open(path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(new)
    if args.json:
        emit({"ok": not failed and not (args.check and changed), "changed": changed, "failed": failed})
    elif not args.diff:
        verb = "would reformat" if args.check else "formatted"
        for p in changed:
            print(f"{verb} {p}")
        if not changed and not failed:
            print("all files are formatted")
    return 1 if failed or (args.check and changed) else 0


# ---- outline / doc / refs / rename ------------------------------------------------------------------------
def cmd_outline(args):
    from .inspect import outline, outline_text
    loaded = load_path(args.file)
    if loaded.program is None:
        print("cannot parse the file; run `klar check` first", file=sys.stderr)
        return 1
    data = outline(loaded, all_modules=args.all)
    if args.json:
        emit({"ok": True, "modules": data})
    else:
        print(outline_text(data))
    return 0


def cmd_doc(args):
    from .inspect import doc_lookup, doc_text
    loaded = load_path(args.file) if args.file else None
    res = doc_lookup(args.query, loaded if loaded is not None and loaded.program is not None else None)
    if args.json:
        emit({"ok": bool(res), "results": res[:args.limit]})
    else:
        print(doc_text(res, args.limit))
    return 0 if res else 1


def cmd_refs(args):
    from .inspect import name_occurrences
    loaded = load_path(args.file)
    if loaded.program is None:
        print("cannot parse the file; run `klar check` first", file=sys.stderr)
        return 1
    occ = name_occurrences(loaded, args.name)
    if args.json:
        emit({"ok": True, "name": args.name, "occurrences": [
            {"file": f, "line": sp.line, "col": sp.col, "role": role,
             "code": loaded.sources[f].split("\n")[sp.line - 1].strip()} for f, sp, role in occ]})
        return 0
    if not occ:
        print(f"`{args.name}` is not used in the program")
        return 1
    for f, sp, role in occ:
        code = loaded.sources[f].split("\n")[sp.line - 1].strip()
        print(f"{f}:{sp.line}:{sp.col:<4} {role:<18} {code[:80]}")
    return 0


def cmd_rename(args):
    from .inspect import rename
    loaded = load_path(args.file)
    if loaded.has_errors():
        print("the program has errors; fix them first (`klar check`) so the rename is exact", file=sys.stderr)
        return 1
    try:
        files, occ = rename(loaded, args.old, args.new)
    except ValueError as ex:
        if args.json:
            emit({"ok": False, "error": str(ex)})
        else:
            print(f"error: {ex}", file=sys.stderr)
        return 1
    if not args.dry_run:
        for path, text in files.items():
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
        # the renamed program must still type-check
        after = load_path(args.file)
        bad = [d for d in after.diags if d.severity == "error"]
        if bad:
            print("warning: the program has errors after the rename:", file=sys.stderr)
            for d in bad[:5]:
                print(f"  {d.span.short()}: {d.message}", file=sys.stderr)
    if args.json:
        emit({"ok": True, "renamed": len(occ), "files": sorted(files)})
    else:
        verb = "would rename" if args.dry_run else "renamed"
        print(f"{verb} {len(occ)} occurrence(s) of `{args.old}` → `{args.new}` in {len(files)} file(s)")
    return 0


# ---- eval / coverage / new --------------------------------------------------------------------------------
def cmd_eval(args):
    from .runtools import evaluate
    res = evaluate(args.code, args.file)
    if args.json:
        emit(res)
        return 0 if res["ok"] else 1
    if res.get("output"):
        sys.stdout.write(res["output"])
    if res["ok"]:
        print(f"{res['value']} : {res['type']}")
        return 0
    if "diagnostics" in res:
        for d in res["diagnostics"]:
            print(f"error[{d['code']}] ({d['where']} line {d['line']}): {d['message']}", file=sys.stderr)
            if d.get("hint"):
                print(f"  hint: {d['hint']}", file=sys.stderr)
    else:
        print(f"runtime error[{res['error']['code']}]: {res['error']['message']}", file=sys.stderr)
    return 1


def cmd_coverage(args):
    from .runtools import coverage, coverage_text
    rep = coverage(args.file, with_main=args.main, runs=args.runs)
    if args.json:
        emit(rep)
    else:
        with open(args.file, encoding="utf-8") as f:
            print(coverage_text(rep, f.read()))
    if not rep["ok"]:
        return 1
    return 1 if args.min is not None and rep["percent"] < args.min else 0


def cmd_new(args):
    from .runtools import new_project
    try:
        files = new_project(args.path)
    except FileExistsError as ex:
        print(f"error: {ex}", file=sys.stderr)
        return 1
    print(f"created {args.path}/: {', '.join(files)}")
    print(f"next: cd {args.path} && klar dev main.klar")
    return 0


def cmd_view(args):
    from .view import collect, render_html, run_trace
    loaded = load_path(args.file)
    if loaded.has_errors() or loaded.program is None:
        print("the program has errors; run `klar check` first", file=sys.stderr)
        return 1
    trace = run_trace(loaded, args.stdin or "") if args.run else None
    data = collect(loaded, trace)
    if args.json:
        emit(data)
        return 0
    out = args.output or os.path.splitext(args.file)[0] + ".view.html"
    with open(out, "w", encoding="utf-8") as f:
        f.write(render_html(data))
    print(f"wrote {out} — open it in a browser")
    if args.open:
        import webbrowser
        webbrowser.open("file://" + os.path.abspath(out))
    return 0


def register(sub):
    p = sub.add_parser("fmt", help="format .klar files in the canonical layout (files or directories)")
    p.add_argument("paths", nargs="*")
    p.add_argument("--check", action="store_true", help="only report files that would change (exit 1)")
    p.add_argument("--diff", action="store_true", help="print a unified diff instead of writing")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_fmt)
    p = sub.add_parser("outline", help="signatures, types and tests of a file — its API in a few lines")
    p.add_argument("file")
    p.add_argument("--all", action="store_true", help="also the imported modules")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_outline)
    p = sub.add_parser("doc", help="look up built-ins, std and project functions: `klar doc split`, `klar doc List.sort`")
    p.add_argument("query")
    p.add_argument("--in", dest="file", help="also search this program and its modules")
    p.add_argument("--limit", type=int, default=12)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_doc)
    p = sub.add_parser("refs", help="where a name is defined and used (exact: Klar has no shadowing)")
    p.add_argument("file")
    p.add_argument("name")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_refs)
    p = sub.add_parser("rename", help="rename a function, type, variable, field or variant everywhere")
    p.add_argument("file")
    p.add_argument("old")
    p.add_argument("new")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_rename)
    p = sub.add_parser("eval", help="evaluate an expression: klar eval '\"a,b\".split(\",\")' (earlier args are statements)")
    p.add_argument("code", nargs="+")
    p.add_argument("--in", dest="file", help="evaluate in the context of this file (its functions and types)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_eval)
    p = sub.add_parser("coverage", help="run the tests and list statements they never execute")
    p.add_argument("file")
    p.add_argument("--main", action="store_true", help="also run main()")
    p.add_argument("--runs", type=int, default=20, help="inputs per property (default 20)")
    p.add_argument("--min", type=float, help="exit 1 if coverage is below this percentage")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_coverage)
    p = sub.add_parser("view", help="write an interactive HTML picture of the program for humans (overview → details)")
    p.add_argument("file")
    p.add_argument("-o", "--output", help="output .html (default: <file>.view.html)")
    p.add_argument("--run", action="store_true", help="also run main() and show call counts, time and output")
    p.add_argument("--stdin", help="input for read_line() during --run")
    p.add_argument("--open", action="store_true", help="open the page in the browser")
    p.add_argument("--json", action="store_true", help="print the underlying data instead")
    p.set_defaults(fn=cmd_view)
    p = sub.add_parser("new", help="create a project skeleton (main.klar with tests, AGENTS.md, README)")
    p.add_argument("path")
    p.set_defaults(fn=cmd_new)
    from .lsp import register as register_lsp
    register_lsp(sub)
    from .repl import register as register_repl
    register_repl(sub)
