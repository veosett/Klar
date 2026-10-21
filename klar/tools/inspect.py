"""Code-navigation tools: `klar outline`, `klar doc`, `klar refs`, `klar rename`.

They exist so that an AI does not have to read whole files: the outline of a module costs a few
dozen tokens, a symbol lookup returns exactly the definition and the usages. Because Klar forbids
shadowing and type names are unique in a program, a name identifies one thing — search and rename
are exact without a full IDE.
"""
import os
import re

from .. import nodes as N
from ..safety import iter_nodes

DECL_KINDS = {N.FnDecl: "fn", N.TypeDecl: "type", N.EnumDecl: "enum", N.AliasDecl: "alias",
              N.ConstDecl: "const", N.TestDecl: "test", N.PropertyDecl: "property", N.UseDecl: "use",
              N.TraitDecl: "trait", N.ImplDecl: "impl"}


def source_lines(loaded, file):
    return loaded.sources.get(file, "").split("\n")


def doc_examples(decls, src_lines, name):
    """The `/// >>> ...` lines of a declaration (the parser turns them into a test `doc: <name>`)."""
    out = []
    for t in decls:
        if isinstance(t, N.TestDecl) and t.name == f"doc: {name}":
            for ln in range(t.span.line, t.span.end_line + 1):
                text = src_lines[ln - 1].strip() if ln - 1 < len(src_lines) else ""
                if text.startswith("///") and text[3:].strip().startswith(">>>"):
                    out.append(text[3:].strip()[3:].strip())
    return out


def type_text(src_lines, t):
    sp = t.span
    line = src_lines[sp.line - 1]
    return line[sp.col - 1:sp.end_col - 1] if sp.line == sp.end_line else line[sp.col - 1:].strip()


def sig_text(src_lines, d):
    """The declaration's text up to (not including) its body, on one line."""
    if isinstance(d, N.TypeDecl):
        tp = f"[{', '.join(d.type_params)}]" if d.type_params else ""
        return f"type {d.name}{tp} {{ " + ", ".join(f"{f.name}: {type_text(src_lines, f.type)}" for f in d.fields) + " }"
    if isinstance(d, N.EnumDecl):
        tp = f"[{', '.join(d.type_params)}]" if d.type_params else ""
        vs = []
        for v in d.variants:
            fs = ", ".join(f"{f.name}: {type_text(src_lines, f.type)}" for f in v.fields)
            vs.append(f"{v.name}({fs})" if v.fields else v.name)
        return f"enum {d.name}{tp} {{ " + ", ".join(vs) + " }"
    if isinstance(d, (N.FnDecl, N.TestDecl, N.PropertyDecl)) and getattr(d, "body", None) is not None:
        end = d.body.span
        lines = src_lines[d.span.line - 1:end.line]
        if not lines:
            return ""
        lines[-1] = lines[-1][:end.col - 1]
        text = " ".join(x.strip() for x in lines)
    else:
        lines = src_lines[d.span.line - 1:d.span.end_line]
        if lines:
            lines[-1] = lines[-1][:d.span.end_col - 1]
            lines[0] = lines[0][d.span.col - 1:]
        text = " ".join(x.strip() for x in lines)
    return re.sub(r"^pub\s+", "", re.sub(r"\s+", " ", text).strip())


def user_modules(loaded):
    return [m for m in loaded.modules if m.program is not None and not getattr(m, "is_sys", False)
            and m.display != "prelude.klar"]


# ---- outline --------------------------------------------------------------------------------------------
def outline(loaded, all_modules=False):
    mods = user_modules(loaded) if all_modules else [loaded.main]
    out = []
    for m in mods:
        lines = source_lines(loaded, m.display)
        items = []
        decls = m.program.decls
        for i, d in enumerate(decls):
            kind = DECL_KINDS.get(type(d))
            if kind is None or (kind == "fn" and d.owner_kind):
                continue
            item = {"kind": kind, "line": d.span.line}
            if kind == "trait":
                item["name"] = d.name
                item["signature"] = ("pub " if d.public else "") + f"trait {d.name}"
                item["methods"] = [sig_text(lines, f) for f in d.methods] + \
                    [sig_text(lines, f) + "   (default)" for f in decls
                     if isinstance(f, N.FnDecl) and f.owner_kind == "default" and f.trait == d.name]
            elif kind == "impl":
                target = getattr(d.target, "name", "?")
                item["name"] = f"{d.trait} for {target}"
                item["signature"] = f"impl {d.trait} for {target}"
                item["methods"] = [sig_text(lines, f) for f in decls[i + 1:i + 1 + len(d.methods)]
                                   if isinstance(f, N.FnDecl) and f.owner_kind == "impl"]
            elif kind in ("test", "property"):
                item["name"] = d.name
            elif kind == "use":
                item["name"] = ".".join(d.path)
                item["items"] = list(d.items)
            else:
                item["name"] = d.name
                item["signature"] = ("pub " if getattr(d, "public", False) else "") + sig_text(lines, d)
                if getattr(d, "public", False):
                    item["public"] = True
            doc = getattr(d, "doc", None)
            if doc:
                first = [x for x in doc.splitlines() if x.strip()]
                if first:
                    item["doc"] = first[0].strip()
            if kind not in ("test", "property", "use", "impl"):
                n = len(doc_examples(m.program.decls, lines, d.name))
                if n:
                    item["doctests"] = n
            if kind == "test" and d.name.startswith("doc: "):
                continue
            items.append(item)
        out.append({"module": m.display, "lines": len(lines), "items": items})
    return out


def outline_text(data):
    res = []
    for mod in data:
        tests = [i for i in mod["items"] if i["kind"] in ("test", "property")]
        res.append(f"{mod['module']} ({mod['lines']} lines, {len(tests)} tests)")
        for i in mod["items"]:
            if i["kind"] == "use":
                res.append(f"  {i['line']:>4}  use {i['name']}.{{{', '.join(i['items'])}}}")
            elif i["kind"] in ("test", "property"):
                continue
            else:
                doc = f"   // {i['doc']}" if i.get("doc") else ""
                dt = f" [{i['doctests']} doc-tests]" if i.get("doctests") else ""
                res.append(f"  {i['line']:>4}  {i['signature']}{doc}{dt}")
                for meth in i.get("methods", []):
                    res.append(f"          {meth}")
        if tests:
            res.append("        tests: " + ", ".join(f"{t['name']!r}" for t in tests))
    return "\n".join(res)


# ---- references -----------------------------------------------------------------------------------------
def name_occurrences(loaded, name):
    """Every place `name` is defined or used, across all user modules: (file, Span, role)."""
    found = []

    def add(file, span, role):
        found.append((file, span, role))

    for m in user_modules(loaded):
        f = m.display
        lines = source_lines(loaded, f)
        for d in m.program.decls:
            if isinstance(d, N.FnDecl):
                for tp, items in (d.bounds or {}).items():
                    for tname, sp in items:
                        if tname == name and not d.owner_kind:
                            add(f, sp, "bound")
            if isinstance(d, N.FnDecl) and d.owner_kind and d.method == name:
                add(f, d.name_span, "method definition")
            elif isinstance(d, N.TraitDecl):
                if d.name == name:
                    add(f, d.name_span, "definition")
                for meth in d.methods:
                    if meth.method == name:
                        add(f, meth.name_span, "method definition")
            elif isinstance(d, N.ImplDecl) and d.trait == name:
                add(f, d.trait_span, "impl")
            elif isinstance(d, (N.FnDecl, N.ConstDecl)) and d.name == name:
                add(f, d.name_span, "definition")
            elif isinstance(d, (N.TypeDecl, N.EnumDecl, N.AliasDecl)) and d.name == name:
                add(f, find_word_span(lines, d.span, name), "definition")
            elif isinstance(d, N.UseDecl):
                for item, sp in zip(d.items, d.item_spans):
                    if item == name:
                        add(f, sp, "import")
        for n in iter_nodes(m.program):
            if isinstance(n, N.Name) and n.name == name:
                add(f, n.span, "use")
            elif isinstance(n, N.Let) and n.name == name:
                add(f, n.name_span, "definition")
            elif isinstance(n, N.Assign) and n.name == name:
                add(f, find_word_span(lines, n.span, name), "assign")
            elif isinstance(n, N.Param) and n.name == name:
                add(f, find_word_span(lines, n.span, name), "parameter")
            elif isinstance(n, N.For) and n.var == name:
                add(f, n.var_span, "definition")
            elif isinstance(n, N.PBind) and n.name == name:
                add(f, n.span, "binding")
            elif isinstance(n, N.MethodCall) and n.method == name and \
                    getattr(n, "resolved", (None,))[0] in ("ufcs", "field_fn", "variant", "trait"):
                add(f, n.method_span, "method call")
            elif isinstance(n, N.FieldAccess) and n.name == name:
                add(f, n.name_span, "field")
            elif isinstance(n, N.TypeName) and n.name == name:
                add(f, find_word_span(lines, n.span, name), "type")
            elif isinstance(n, N.RecordLit) and n.type_name == name:
                add(f, find_word_span(lines, n.span, name), "type")
            elif isinstance(n, N.PVariant) and (n.enum == name or n.variant == name):
                add(f, find_word_span(lines, n.span, name), "pattern")
            elif isinstance(n, N.FieldInit) and n.name == name:
                add(f, find_word_span(lines, n.span, name), "field")
            elif isinstance(n, N.Arg) and n.name == name:
                add(f, find_word_span(lines, n.span, name), "named argument")
            elif isinstance(n, N.FieldDecl) and n.name == name:
                add(f, find_word_span(lines, n.span, name), "field definition")
            elif isinstance(n, N.VariantDecl) and n.name == name:
                add(f, find_word_span(lines, n.span, name), "variant definition")
    seen, uniq = set(), []
    for f, sp, role in found:
        if sp is None:
            continue
        key = (f, sp.line, sp.col)
        if key not in seen:
            seen.add(key)
            uniq.append((f, sp, role))
    uniq.sort(key=lambda x: (x[0], x[1].line, x[1].col))
    return uniq


def find_word_span(lines, span, word):
    """Span of the first whole-word occurrence of `word` inside `span`."""
    from ..diagnostics import Span
    for ln in range(span.line, span.end_line + 1):
        if ln - 1 >= len(lines):
            break
        text = lines[ln - 1]
        start = span.col - 1 if ln == span.line else 0
        stop = span.end_col - 1 if ln == span.end_line else len(text)
        for m in re.finditer(rf"\b{re.escape(word)}\b", text):
            if start <= m.start() < max(stop, start + 1):
                return Span(span.file, ln, m.start() + 1, ln, m.end() + 1)
    return None


# ---- rename -----------------------------------------------------------------------------------------------
def rename(loaded, old, new):
    """{file path: new text}; raises ValueError when the rename is unsafe."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", new):
        raise ValueError(f"`{new}` is not a valid name")
    if old[:1].isupper() != new[:1].isupper():
        raise ValueError("a rename must keep the case convention (types/variants PascalCase, values snake_case)")
    if name_occurrences(loaded, new):
        raise ValueError(f"`{new}` is already used in the program (Klar forbids shadowing)")
    occ = name_occurrences(loaded, old)
    if not occ:
        raise ValueError(f"`{old}` is not used in the program")
    paths = {m.display: m.path for m in user_modules(loaded)}
    by_file = {}
    for f, sp, _ in occ:
        by_file.setdefault(f, []).append(sp)
    result = {}
    for f, spans in by_file.items():
        lines = loaded.sources[f].split("\n")
        for sp in sorted(spans, key=lambda s: (s.line, s.col), reverse=True):
            text = lines[sp.line - 1]
            seg = text[sp.col - 1:sp.col - 1 + len(old)]
            if seg != old:
                continue
            lines[sp.line - 1] = text[:sp.col - 1] + new + text[sp.col - 1 + len(old):]
        result[paths[f]] = "\n".join(lines)
    return result, occ


# ---- doc ----------------------------------------------------------------------------------------------------
def builtin_examples(name, limit=3):
    """Usage lines from the built-in test-suite (always correct: they are tested)."""
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path = os.path.join(here, "tests", "stdlib", "builtins_test.klar")
    if not os.path.exists(path):
        return []
    out = []
    pat = re.compile(rf"(\.|\b){re.escape(name)}\(")
    with open(path, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s.startswith("assert") and pat.search(s):
                out.append(s.split("//")[0].strip())
                if len(out) >= limit:
                    break
    return out


def doc_lookup(query, loaded=None):
    """Matches for `name`, `Type.method` or a fragment: built-ins, std modules and the given program."""
    from ..builtins import GLOBALS, METHODS
    from ..parser import parse
    q = query.strip()
    owner, _, meth = q.rpartition(".") if "." in q else ("", "", q)
    results = []

    def match(name):
        return name == meth or (len(meth) >= 3 and meth.lower() in name.lower())

    for name, (sig, _) in GLOBALS.items():
        if not owner and match(name):
            results.append({"kind": "built-in function", "name": name, "signature": sig,
                            "examples": builtin_examples(name), "exact": name == meth})
    for typ, ms in METHODS.items():
        if owner and owner != typ:
            continue
        for name, (sig, _) in ms.items():
            if match(name):
                results.append({"kind": f"{typ} method", "name": f"{typ}.{name}", "signature": sig,
                                "examples": builtin_examples(name), "exact": name == meth})
    std_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "std")
    for fname in sorted(os.listdir(std_dir)):
        if not fname.endswith(".klar"):
            continue
        with open(os.path.join(std_dir, fname), encoding="utf-8") as f:
            src = f.read()
        prog = parse(src, fname)
        lines = src.split("\n")
        for d in prog.decls:
            if isinstance(d, N.FnDecl) and not d.owner_kind and not owner and match(d.name):
                results.append(decl_doc(d, lines, f"std.{fname[:-5]}", d.name == meth, prog.decls))
            elif isinstance(d, (N.TraitDecl, N.FnDecl)):
                results += trait_docs(d, lines, f"std.{fname[:-5]}", owner, meth, match, prog.decls)
    if loaded is not None:
        for m in user_modules(loaded):
            lines = source_lines(loaded, m.display)
            for d in m.program.decls:
                if isinstance(d, (N.FnDecl, N.TypeDecl, N.EnumDecl, N.ConstDecl, N.AliasDecl)) and \
                        not getattr(d, "owner_kind", None) and not owner and match(d.name):
                    results.append(decl_doc(d, lines, m.display, d.name == meth, m.program.decls))
                elif isinstance(d, (N.TraitDecl, N.FnDecl)):
                    results += trait_docs(d, lines, m.display, owner, meth, match, m.program.decls)
    results.sort(key=lambda r: (not r["exact"], r["name"]))
    return results


def trait_docs(d, lines, where, owner, meth, match, decls):
    """Doc entries for a trait (`klar doc Shape`) or a trait/impl method (`klar doc area`, `Circle.area`)."""
    loc = f"use {where}.{{...}}" if where.startswith("std.") else f"{where}:{d.span.line}"
    if isinstance(d, N.TraitDecl):
        if owner or not match(d.name):
            return []
        ms = [sig_text(lines, f) for f in d.methods]
        ms += [sig_text(lines, f) + " (default)" for f in decls
               if isinstance(f, N.FnDecl) and f.owner_kind == "default" and f.trait == d.name]
        text = " ".join(x.strip() for x in (d.doc or "").splitlines() if x.strip())
        return [{"kind": f"trait ({loc})", "name": d.name, "signature": f"trait {d.name} {{ " + "; ".join(ms) + " }",
                 "doc": text, "examples": doc_examples(decls, lines, d.name)[:3], "exact": d.name == meth}]
    if not d.owner_kind or not match(d.method) or (owner and owner not in (d.owner, d.trait)):
        return []
    r = decl_doc(d, lines, where, d.method == meth, decls)
    r["kind"] = (f"method of `impl {d.trait} for {d.owner}` ({loc})" if d.owner_kind == "impl"
                 else f"default method of trait `{d.trait}` ({loc})")
    return [r]


def decl_doc(d, lines, where, exact, decls=()):
    doc = getattr(d, "doc", None) or ""
    text = [x.strip() for x in doc.splitlines() if x.strip()]
    ex = doc_examples(decls, lines, d.name)
    hint = f"use {where}.{{{d.name}}}" if where.startswith("std.") else f"{where}:{d.span.line}"
    return {"kind": DECL_KINDS.get(type(d), "decl") + f" ({hint})", "name": d.name, "signature": sig_text(lines, d),
            "doc": " ".join(text), "examples": ex[:3], "exact": exact}


def doc_text(results, limit=12):
    if not results:
        return "nothing found (try a shorter fragment, e.g. `klar doc split`)"
    out = []
    for r in results[:limit]:
        out.append(f"{r['signature']}")
        out.append(f"    {r['kind']}" + (f" — {r['doc']}" if r.get("doc") else ""))
        for e in r.get("examples", []):
            out.append(f"    e.g. {e}")
    if len(results) > limit:
        out.append(f"... {len(results) - limit} more (narrow the query, e.g. `List.{results[0]['name'].split('.')[-1]}`)")
    return "\n".join(out)
