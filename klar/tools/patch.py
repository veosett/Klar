"""`klar patch`: structured, verified edits for AI authors (the "AI patch" protocol).

Instead of rewriting a whole file or matching fragile line numbers, an edit names *what* it changes:

    {"edits": [
      {"replace": "area",           "with": "fn area(s: Shape) -> Float { ... }"},   // a declaration by name
      {"replace": "Circle.area",    "with": "..."},                                  // an impl / trait method
      {"replace": "test:totals",    "with": "test \"totals\" { ... }"},              // a test block
      {"insert": "fn helper() -> Int { return 1 }", "after": "area"},               // or "before", or "at": "end"
      {"delete": "old_fn"},
      {"id": 42, "with": "x + 1"},              // any node, by the id `klar ast` prints
      {"find": "let n = 0", "replace": "let n = 1", "in": "main"},   // exact text, must be unique ("in" optional)
      {"rename": "total", "to": "sum"}         // a name everywhere (like `klar rename`)
    ], "test": true}

All edits refer to the file as it was before the patch; they are applied together, then the program is checked
(and its tests run with "test": true). The file is written only when the result has no new errors and no failing
tests — otherwise nothing changes and the report says why, with the usual compact diagnostics. A doc comment above
a replaced declaration is kept unless the new code brings its own `///` lines. A formatted file stays formatted.
"""
import difflib
import io
import json
import os
import sys

from .. import nodes as N
from ..diagnostics import KlarSyntaxError
from ..loader import load_source
from ..parser import parse


class PatchError(Exception):
    pass


def decl_targets(prog):
    """{target name: node} for the top-level declarations of a program."""
    out = {}
    for d in prog.decls:
        if isinstance(d, N.FnDecl):
            out[d.name] = d
        elif isinstance(d, (N.TypeDecl, N.EnumDecl, N.ConstDecl, N.AliasDecl, N.TraitDecl)):
            out[d.name] = d
        elif isinstance(d, N.TestDecl):
            out["test:" + d.name] = d
        elif isinstance(d, N.PropertyDecl):
            out["property:" + d.name] = d
        elif isinstance(d, N.ImplDecl):
            target = getattr(d.target, "name", "?")
            out[f"impl {d.trait} for {target}"] = d
    return out


class Text:
    """Line/column <-> offset for the original source."""

    def __init__(self, src):
        self.src = src
        self.starts = [0]
        for i, ch in enumerate(src):
            if ch == "\n":
                self.starts.append(i + 1)

    def off(self, line, col):
        return self.starts[line - 1] + col - 1

    def span(self, sp):
        return self.off(sp.line, sp.col), self.off(sp.end_line, sp.end_col)

    def line_start(self, offset):
        return self.src.rfind("\n", 0, offset) + 1

    def line_end(self, offset):
        i = self.src.find("\n", offset)
        return len(self.src) if i < 0 else i

    def doc_start(self, offset):
        """The start of the `///` lines right above the line holding `offset` (or that line's start)."""
        start = self.line_start(offset)
        while start > 0:
            prev = self.line_start(start - 1)
            if self.src[prev:start].strip().startswith("///"):
                start = prev
            else:
                break
        return start


def unknown(name, targets):
    close = difflib.get_close_matches(name, list(targets), n=3, cutoff=0.5)
    hint = f"; did you mean {', '.join('`' + c + '`' for c in close)}?" if close else ""
    return PatchError(f"no declaration `{name}` in the file{hint} (targets: names, `Type.method`, `test:name`)")


def plan(src, display, edits):
    """The text ranges the edits replace: [(start, end, new text)], plus the renames to apply afterwards."""
    t = Text(src)
    try:
        prog = parse(src, display)
    except KlarSyntaxError:
        prog = None
    targets = decl_targets(prog) if prog else {}
    nodes = N.number(prog) if prog else {}
    changes, renames = [], []

    def decl(name):
        if name not in targets:
            raise unknown(name, targets)
        return targets[name]

    for k, e in enumerate(edits):
        if not isinstance(e, dict):
            raise PatchError(f"edit #{k + 1} is not an object")
        if "replace" in e and "with" in e:
            d = decl(e["replace"])
            a, b = t.span(d.span)
            code = e["with"].strip("\n")
            a = t.doc_start(a) if code.lstrip().startswith("///") else t.line_start(a)
            changes.append((a, b, code))
        elif "insert" in e:
            code = e["insert"].strip("\n")
            if "after" in e:
                _, b = t.span(decl(e["after"]).span)
                b = t.line_end(b)
                changes.append((b, b, "\n\n" + code))
            elif "before" in e:
                a, _ = t.span(decl(e["before"]).span)
                a = t.doc_start(a)
                changes.append((a, a, code + "\n\n"))
            elif e.get("at") == "end":
                end = len(src.rstrip("\n"))
                changes.append((end, end, "\n\n" + code))
            else:
                raise PatchError(f"edit #{k + 1}: `insert` needs `after`, `before` or `\"at\": \"end\"`")
        elif "delete" in e:
            d = decl(e["delete"])
            a, b = t.span(d.span)
            a = t.doc_start(a)
            b = t.line_end(b)
            # also one blank line that separated it from the next declaration
            if src[b:b + 2] == "\n\n":
                b += 1
            if b < len(src) and src[b] == "\n":
                b += 1
            changes.append((a, b, ""))
        elif "id" in e and "with" in e:
            n = nodes.get(e["id"])
            if n is None:
                raise PatchError(f"edit #{k + 1}: no node with id {e['id']} (ids come from `klar ast` of this file)")
            a, b = t.span(n.span)
            changes.append((a, b, e["with"]))
        elif "find" in e and "replace" in e:
            lo, hi = 0, len(src)
            if "in" in e:
                lo, hi = t.span(decl(e["in"]).span)
            region = src[lo:hi]
            count = region.count(e["find"])
            where = f" in `{e['in']}`" if "in" in e else ""
            if count != 1:
                raise PatchError(f"edit #{k + 1}: the text to find occurs {count} times{where} (it must be unique: "
                                 "add surrounding text or use `in`)")
            a = lo + region.index(e["find"])
            changes.append((a, a + len(e["find"]), e["replace"]))
        elif "rename" in e and "to" in e:
            renames.append((e["rename"], e["to"]))
        else:
            raise PatchError(f"edit #{k + 1}: unknown edit {sorted(e)} (replace/with, insert, delete, id/with, "
                             "find/replace, rename/to)")
    changes.sort(key=lambda c: (c[0], c[1]))
    for (a1, b1, _), (a2, b2, _) in zip(changes, changes[1:]):
        if a2 < b1 or (a1 == b1 == a2 == b2):
            raise PatchError("two edits change the same part of the file")
    return changes, renames


def apply_changes(src, changes):
    out = src
    for a, b, text in sorted(changes, key=lambda c: (c[0], c[1]), reverse=True):
        out = out[:a] + text + out[b:]
    return out


def errors_of(loaded):
    from ..cli import user_diags
    return [d for d in user_diags(loaded) if d.severity == "error"]


def run_tests(loaded):
    """[(name, error or None)] of the program's tests in the interpreter."""
    from ..cli import runtime_guard
    from ..interpreter import Interpreter
    interp = Interpreter(loaded, out=io.StringIO(), err_stream=io.StringIO())
    out = []
    for t in interp.tests:
        _, err = runtime_guard(lambda: interp.run_test(t, runs=20, seed=0), interp)
        out.append((t.name, err))
    return out


def patch_file(path, patch, write=True, force=False):
    """Applies a patch ({"edits": [...], "test": bool}) to a file; returns the report (a JSON-ready dict)."""
    from ..cli import compact, compact_rt
    path = os.path.abspath(path)
    root, display = os.path.dirname(path), os.path.basename(path)
    with open(path, encoding="utf-8") as f:
        src = f.read()
    edits = patch.get("edits", []) if isinstance(patch, dict) else patch
    report = {"ok": False, "written": False, "file": path}
    try:
        changes, renames = plan(src, display, edits)
    except PatchError as ex:
        report["error"] = str(ex)
        return report
    new = apply_changes(src, changes)
    files = {path: new}
    for old, to in renames:
        from .inspect import rename
        loaded = load_source(new, display, root)
        try:
            result, _ = rename(loaded, old, to)
        except ValueError as ex:
            report["error"] = f"rename `{old}` → `{to}`: {ex}"
            return report
        for p, text in result.items():
            if os.path.abspath(p) == path:
                new = text
            else:
                files[os.path.abspath(p)] = text
        files[path] = new
    from .fmt import FormatError, format_checked
    try:
        if format_checked(src) == src:
            new = format_checked(new)
            files[path] = new
    except FormatError:
        pass
    before = load_source(src, display, root)
    overlay = {p: t for p, t in files.items() if p != path}
    after = load_source(new, display, root, overlay=overlay)
    old_errs = {(d.code, d.message) for d in errors_of(before)}
    new_errs = [d for d in errors_of(after) if (d.code, d.message) not in old_errs]
    report["applied"] = len(edits)
    report["diff"] = "".join(difflib.unified_diff(src.splitlines(True), new.splitlines(True), display,
                                                  display + " (patched)"))
    if new_errs:
        report["errors"] = [compact(d) for d in new_errs]
    if patch.get("test") if isinstance(patch, dict) else False:
        if not new_errs:
            results = run_tests(after)
            failed = [{"name": n, **compact_rt(e)} for n, e in results if e is not None]
            report["tests"] = {"passed": sum(1 for _, e in results if e is None), "failed": failed}
        else:
            report["tests"] = {"skipped": "the patched program has errors"}
    failed_tests = bool(report.get("tests", {}).get("failed"))
    report["ok"] = not new_errs and not failed_tests
    if write and (report["ok"] or force):
        for p, text in files.items():
            with open(p, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
        report["written"] = True
    return report


def cmd_patch(args):
    if args.patch == "-":
        text = sys.stdin.read()
    elif os.path.isfile(args.patch):
        with open(args.patch, encoding="utf-8") as f:
            text = f.read()
    else:
        text = args.patch                         # the JSON itself
    try:
        patch = json.loads(text)
    except json.JSONDecodeError as ex:
        print(json.dumps({"ok": False, "error": f"the patch is not valid JSON: {ex}"}))
        return 1
    if args.test and isinstance(patch, dict):
        patch["test"] = True
    report = patch_file(args.file, patch, write=not args.dry_run, force=args.force)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    else:
        if "error" in report:
            print(f"error: {report['error']}", file=sys.stderr)
        else:
            sys.stdout.write(report["diff"])
            for e in report.get("errors", []):
                print(f"error[{e['code']}] {e['at']}: {e['msg']}" + (f"\n  hint: {e['hint']}" if "hint" in e else ""))
            tests = report.get("tests")
            if tests and "failed" in tests:
                print(f"tests: {tests['passed']} passed, {len(tests['failed'])} failed")
                for f in tests["failed"]:
                    print(f"  FAIL {f['name']}: {f['code']} {f['msg']}")
            if report["written"]:
                print(f"patched {report['file']}")
            elif not report["ok"]:
                print("not written: the patch would break the program (use --force to write anyway)")
            else:
                print("not written (--dry-run)")
    return 0 if report["ok"] else 1


def register(sub):
    p = sub.add_parser("patch", help="apply structured edits (by declaration name or node id) and verify them")
    p.add_argument("file")
    p.add_argument("patch", help="a JSON file, `-` for stdin, or the JSON text itself")
    p.add_argument("--test", action="store_true", help="also run the tests; failing tests reject the patch")
    p.add_argument("--dry-run", action="store_true", help="only report (diff, errors, tests)")
    p.add_argument("--force", action="store_true", help="write even if the result has errors")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_patch)
