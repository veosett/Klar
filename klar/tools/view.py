"""`klar view`: an interactive picture of what a program does, for human reviewers.

Produces ONE self-contained HTML file (no network, no dependencies):
  * overview — what the program is, its entry point, effects, how many functions/types/tests;
  * call graph — who calls whom, starting at `main`; pure functions vs. functions with effects
    (`io`, `fs`, ...); with `--run`, how often each function was called in a real run;
  * per function, on demand — a plain-language summary (inputs, result, contracts, effects,
    which errors it can return, what it calls), then the control flow as nested blocks that can be
    expanded level by level, then the source and the tests that exercise it;
  * the data types (records and enums).
"""
import html
import io
import json
import os
import re

from .. import nodes as N
from ..safety import iter_nodes
from .inspect import doc_examples, sig_text, source_lines, type_text, user_modules

TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "view_template.html")


def seg(lines, span):
    """Source text of a span, whitespace collapsed."""
    if span is None:
        return ""
    if span.line == span.end_line:
        text = lines[span.line - 1][span.col - 1:span.end_col - 1]
    else:
        parts = [lines[span.line - 1][span.col - 1:]]
        parts += lines[span.line:span.end_line - 1]
        parts.append(lines[span.end_line - 1][:span.end_col - 1])
        text = " ".join(p.strip() for p in parts)
    return re.sub(r"\s+", " ", text).strip()


def short(text, n=90):
    return text if len(text) <= n else text[:n - 1] + "…"


# ---- control flow as a tree of blocks ------------------------------------------------------------
def flow(stmts, lines):
    out = []
    for s in stmts:
        out.append(flow_stmt(s, lines))
    return out


def flow_expr(e, lines):
    """Expressions with their own structure (match) become blocks; others become text."""
    if isinstance(e, N.Match):
        arms = []
        for a in e.arms:
            pat = seg(lines, a.pattern.span)
            if a.guard is not None:
                pat += " if " + seg(lines, a.guard.span)
            body = flow(a.body.stmts, lines) if isinstance(a.body, N.Block) else [flow_expr(a.body, lines)]
            arms.append({"pattern": pat, "body": body, "line": a.span.line})
        return {"kind": "match", "subject": seg(lines, e.subject.span), "arms": arms, "line": e.span.line}
    return {"kind": "expr", "text": short(seg(lines, e.span), 140), "line": e.span.line}


def flow_stmt(s, lines):
    line = s.span.line
    if isinstance(s, N.Let):
        node = {"kind": "let", "name": s.name, "mutable": s.mutable, "line": line}
        if isinstance(s.value, N.Match):
            node["value"] = flow_expr(s.value, lines)
        else:
            node["text"] = short(seg(lines, s.value.span), 120)
        return node
    if isinstance(s, N.Assign):
        node = {"kind": "assign", "name": s.name, "line": line}
        if isinstance(s.value, N.Match):
            node["value"] = flow_expr(s.value, lines)
        else:
            node["text"] = short(seg(lines, s.value.span), 120)
        return node
    if isinstance(s, N.Return):
        if s.value is None:
            return {"kind": "return", "text": "", "line": line}
        if isinstance(s.value, N.Match):
            return {"kind": "return", "value": flow_expr(s.value, lines), "line": line}
        return {"kind": "return", "text": short(seg(lines, s.value.span), 120), "line": line}
    if isinstance(s, N.If):
        node = {"kind": "if", "cond": seg(lines, s.cond.span), "then": flow(s.then.stmts, lines), "line": line}
        if isinstance(s.else_, N.If):
            node["else"] = [flow_stmt(s.else_, lines)]
        elif s.else_ is not None:
            node["else"] = flow(s.else_.stmts, lines)
        return node
    if isinstance(s, N.While):
        return {"kind": "while", "cond": seg(lines, s.cond.span), "body": flow(s.body.stmts, lines), "line": line}
    if isinstance(s, N.For):
        return {"kind": "for", "var": s.var, "iter": seg(lines, s.iter.span), "body": flow(s.body.stmts, lines),
                "line": line}
    if isinstance(s, N.Assert):
        return {"kind": "assert", "text": seg(lines, s.cond.span), "line": line}
    if isinstance(s, N.Break):
        return {"kind": "break", "line": line}
    if isinstance(s, N.Continue):
        return {"kind": "continue", "line": line}
    if isinstance(s, N.ExprStmt):
        return flow_expr(s.expr, lines)
    return {"kind": "expr", "text": short(seg(lines, s.span)), "line": line}


# ---- facts about a function --------------------------------------------------------------------------
def calls_in(node, user_fns, trait_targets=None):
    """User functions called in `node`. A call through a trait (`x.area()` with `x: T`, `T: Shape`) may reach
    every implementation of that method, so it links to all of them."""
    found = []
    for n in iter_nodes(node):
        names = []
        res = getattr(n, "resolved", (None,)) if isinstance(n, N.MethodCall) else (None,)
        if isinstance(n, N.Call) and isinstance(n.callee, N.Name) and n.callee.name in user_fns:
            names = [n.callee.name]
        elif isinstance(n, N.Name) and n.name in user_fns and getattr(n, "sig", None) is not None:
            names = [n.name]  # a function passed as a value (`xs.map(f)`)
        elif res[0] == "ufcs" and res[2] in user_fns:
            names = [res[2]]
        elif res[0] == "trait":
            names = [t for t in (trait_targets or {}).get((res[1], res[2]), []) if t in user_fns]
        for name in names:
            if name not in found:
                found.append(name)
    return found


def trait_targets_of(loaded):
    out = {}
    for methods in loaded.universe.type_methods.values():
        for m, (trait, sig) in methods.items():
            lst = out.setdefault((trait, m), [])
            if sig.name not in lst:
                lst.append(sig.name)
    return out


def builtins_used(node):
    names = []
    for n in iter_nodes(node):
        if isinstance(n, N.Call) and isinstance(n.callee, N.Name) and n.callee.name in (
                "print", "read_line", "read_file", "write_file", "file_exists", "now_ms", "now_ns", "random_int",
                "cli_args", "fail", "todo", "dbg"):
            if n.callee.name not in names:
                names.append(n.callee.name)
    return names


def errors_returned(fn, lines):
    """The `Err(...)` / `None` values a function returns explicitly (what can go wrong)."""
    out = []
    for n in iter_nodes(fn.body):
        if isinstance(n, N.Return) and n.value is not None:
            v = n.value
            if isinstance(v, N.Call) and isinstance(v.callee, N.Name) and v.callee.name == "Err" and v.args:
                text = seg(lines, v.args[0].value.span)
                text = re.sub(r"\(.*\)$", "(…)", text)
                if text not in out:
                    out.append(text)
            elif isinstance(v, N.Name) and v.name == "None" and "None" not in out:
                out.append("None")
        if isinstance(n, N.Try) and "?" not in out:
            out.append("?")
    return out


def summary(fn, lines, calls, errs, effects, used):
    ps = ", ".join(f"{p.name} ({type_text(lines, p.type)})" for p in fn.params)
    ret = type_text(lines, fn.ret) if fn.ret else "nothing (Unit)"
    parts = []
    doc = (fn.doc or "").strip()
    if doc:
        parts.append(doc.splitlines()[0])
    parts.append(f"Takes {ps}." if ps else "Takes no arguments.")
    parts.append(f"Returns {ret}.")
    for r in fn.requires:
        parts.append(f"Requires {seg(lines, r.span)}.")
    for e in fn.ensures:
        parts.append(f"Guarantees {seg(lines, e.span)}.")
    if effects:
        what = {"io": "console input/output", "fs": "files", "time": "the clock", "rand": "random numbers",
                "net": "the network"}
        parts.append("Side effects: " + ", ".join(what.get(x, x) for x in effects) + ".")
    else:
        parts.append("Pure: no side effects (same input → same output).")
    if errs:
        parts.append("Can return: " + ", ".join("errors of the functions it calls (via ?)" if e == "?" else e
                                                for e in errs) + ".")
    if calls:
        parts.append("Calls " + ", ".join(calls) + ".")
    if used:
        parts.append("Uses built-ins " + ", ".join(used) + ".")
    return " ".join(parts)


# ---- the whole program ----------------------------------------------------------------------------------------
def collect(loaded, trace=None):
    mods = user_modules(loaded)
    fns, types, consts, tests = {}, [], [], []
    user_fns = set()
    targets = trait_targets_of(loaded)
    for m in mods:
        for d in m.program.decls:
            if isinstance(d, N.FnDecl) and not d.constructs:      # (a newtype's constructor is shown with its type)
                user_fns.add(d.name)
    for m in mods:
        lines = source_lines(loaded, m.display)
        own = m is loaded.main
        for d in m.program.decls:
            if isinstance(d, N.FnDecl) and not d.constructs:
                calls = calls_in(d.body, user_fns, targets)
                calls += [c for r in d.requires + d.ensures for c in calls_in(r, user_fns, targets)
                          if c not in calls]
                errs = errors_returned(d, lines)
                tried = [n.expr.callee.name for n in iter_nodes(d.body) if isinstance(n, N.Try)
                         and isinstance(n.expr, N.Call) and isinstance(n.expr.callee, N.Name)]
                used = builtins_used(d.body)
                fns[d.name] = {
                    "name": d.name, "module": m.display, "line": d.span.line, "end_line": d.body.span.end_line,
                    "own": own, "signature": sig_text(lines, d), "doc": (d.doc or "").strip(),
                    "effects": list(d.effects), "calls": calls, "called_by": [],
                    "summary": summary(d, lines, calls, errs, d.effects, used),
                    "params": [{"name": p.name, "type": (d.owner if d.owner_kind == "impl" else "Self")
                                if p.name == "self" and d.owner_kind else type_text(lines, p.type)}
                               for p in d.params],
                    "returns": type_text(lines, d.ret) if d.ret else "Unit", "builtins": used,
                    "requires": [seg(lines, r.span) for r in d.requires],
                    "ensures": [seg(lines, e.span) for e in d.ensures],
                    "errors": errs, "tried": tried, "flow": flow(d.body.stmts, lines),
                    "source": "\n".join(lines[d.span.line - 1:d.body.span.end_line]),
                    "examples": doc_examples(m.program.decls, lines, d.name), "tests": [],
                    "statements": sum(1 for n in iter_nodes(d.body) if isinstance(n, N.Block) for _ in n.stmts),
                }
            elif isinstance(d, N.TypeDecl):
                types.append({"kind": "record", "name": d.name, "module": m.display, "line": d.span.line,
                              "doc": (d.doc or "").strip(),
                              "fields": [f"{f.name}: {type_text(lines, f.type)}" for f in d.fields]})
            elif isinstance(d, N.EnumDecl):
                types.append({"kind": "enum", "name": d.name, "module": m.display, "line": d.span.line,
                              "doc": (d.doc or "").strip(),
                              "fields": [v.name + (f"({', '.join(f'{f.name}: {type_text(lines, f.type)}' for f in v.fields)})"
                                                   if v.fields else "") for v in d.variants]})
            elif isinstance(d, N.TraitDecl):
                sigs = [sig_text(lines, f) for f in d.methods] + \
                    [sig_text(lines, f) + "  (default)" for f in m.program.decls
                     if isinstance(f, N.FnDecl) and f.owner_kind == "default" and f.trait == d.name]
                types.append({"kind": "trait", "name": d.name, "module": m.display, "line": d.span.line,
                              "doc": (d.doc or "").strip(), "fields": sigs,
                              "impls": sorted(t for (tr, t) in loaded.universe.impls if tr == d.name)})
            elif isinstance(d, N.AliasDecl):
                types.append({"kind": "alias", "name": d.name, "module": m.display, "line": d.span.line,
                              "doc": (d.doc or "").strip(), "fields": [type_text(lines, d.target)]})
            elif isinstance(d, N.ConstDecl):
                consts.append({"name": d.name, "value": seg(lines, d.value.span), "line": d.span.line})
            elif isinstance(d, (N.TestDecl, N.PropertyDecl)) and own:
                called = calls_in(d.body, user_fns, targets)
                tests.append({"name": d.name, "kind": "property" if isinstance(d, N.PropertyDecl) else
                              ("doc-test" if d.name.startswith("doc: ") else "test"),
                              "line": d.span.line, "calls": called})
                for c in called:
                    if c in fns or c in user_fns:
                        pass
    # errors passed on with `?` are the callee's errors: resolve them (a few rounds for chains)
    for _ in range(4):
        for f in fns.values():
            for c in f.get("tried", []):
                for e in fns.get(c, {}).get("errors", []):
                    if e != "?" and e not in f["errors"]:
                        f["errors"].append(e)
    for f in fns.values():
        if f.get("tried") and all(c in fns for c in f["tried"]) and "?" in f["errors"]:
            f["errors"].remove("?")
    # keep the program's own functions and the imported ones it actually reaches
    keep = {n for n, f in fns.items() if f["own"]}
    work = list(keep) + [c for t in tests for c in t["calls"]]
    while work:
        n = work.pop()
        if n in fns:
            keep.add(n)
            work.extend(c for c in fns[n]["calls"] if c not in keep)
    fns = {n: f for n, f in fns.items() if n in keep}
    for t in tests:
        for c in t["calls"]:
            if c in fns:
                fns[c]["tests"].append(t["name"])
    for f in fns.values():
        for c in f["calls"]:
            if c in fns and f["name"] not in fns[c]["called_by"]:
                fns[c]["called_by"].append(f["name"])
    main = fns.get("main")
    first_doc = ""
    src0 = source_lines(loaded, loaded.main.display)
    for ln in src0:
        s = ln.strip()
        if s.startswith("//") and not s.startswith("///"):
            first_doc += s[2:].strip() + " "
        elif s:
            break
    data = {
        "file": loaded.main.display, "modules": [m.display for m in mods],
        "description": (main["doc"] if main and main["doc"] else first_doc).strip(),
        "entry": "main" if main else None, "functions": fns, "types": types, "consts": consts, "tests": tests,
        "trace": trace,
    }
    return data


def run_trace(loaded, stdin=""):
    from ..errors import KlarRuntimeError
    from ..interpreter import Interpreter, Profiler, run_with_big_stack
    out = io.StringIO()
    interp = Interpreter(loaded, out=out, inp=io.StringIO(stdin), err_stream=io.StringIO())
    interp.prof = prof = Profiler()
    error = None
    try:
        run_with_big_stack(interp.run_main)
    except KlarRuntimeError as ex:
        error = {"code": ex.code, "message": ex.message, "line": ex.span.line}
    prof.finish()
    calls = {}
    for key, (n, total, slf) in prof.funcs.items():
        if not key.startswith("<builtin>"):
            calls[key.split(" (")[0]] = {"calls": n, "ms": round(total * 1000, 3), "self_ms": round(slf * 1000, 3)}
    return {"calls": calls, "output": out.getvalue()[:4000], "error": error,
            "total_ms": round(prof.total() * 1000, 3)}


def render_html(data):
    with open(TEMPLATE, encoding="utf-8") as f:
        tpl = f.read()
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return tpl.replace("/*__DATA__*/null", payload).replace("__TITLE__", html.escape(data["file"]))
