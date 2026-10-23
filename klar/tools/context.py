"""`klar context <file> <name>`: the smallest context a model needs to change one function, type or constant — its
source with the documentation, the signatures of what it uses, its tests and its callers — within a token budget.

Names are found by the words of the source (Klar has no shadowing, so a word that names a function, type or
constant of the program is that declaration); compiler/context.klar gives the same answer in klarc.
"""
from .. import nodes as N
from ..lexer import tokenize
from .inspect import sig_text, source_lines, user_modules

DEFAULT_TOKENS = 2000


def tokens_of(text):
    """A rough token count of text (about 4 characters per token)."""
    return (len(text) + 3) // 4


def words(src):
    """(line, word) for every identifier of the source that may name a declaration: not a field after `.` (but a
    method call `x.f()` is), including the code inside `{...}` of strings."""
    out = []

    def scan(toks, line=None):
        for i, t in enumerate(toks):
            if t.kind == "IDENT":
                prev = toks[i - 1] if i > 0 else None
                nxt = toks[i + 1] if i + 1 < len(toks) else None
                if prev is not None and prev.kind == "OP" and prev.value == ".":
                    if not (nxt is not None and nxt.kind == "OP" and nxt.value == "("):
                        continue
                out.append((line if line is not None else t.span.line, t.value))
            elif t.kind == "STR" and t.parts:
                for part in t.parts:
                    if isinstance(part, tuple) and part[0] == "expr":
                        try:
                            inner = tokenize(part[1], "<string>")
                        except Exception:  # noqa: BLE001 (a broken interpolation names nothing)
                            continue
                        scan(inner, part[2])

    try:
        scan(tokenize(src, "<context>"))
    except Exception:  # noqa: BLE001 (the program could not be read: no words)
        return []
    return out


class Item:
    """A top-level declaration: what it is called, how it is shown and which lines it covers."""

    def __init__(self, d, module, lines):
        self.d = d
        self.file = module
        self.kind = kind_of(d)
        self.name = name_of(d)
        self.word = d.method if isinstance(d, N.FnDecl) and d.owner_kind else self.name
        self.first = doc_start(lines, d.span.line)
        self.line = d.span.line
        self.last = d.span.end_line
        if self.kind in ("test", "property"):
            self.signature = f'{self.kind} "{d.name}"'
        else:
            self.signature = sig_text(lines, d)

    def source(self, lines):
        return "\n".join(lines[self.first - 1:self.last])


def kind_of(d):
    if isinstance(d, N.FnDecl):
        return "fn"
    return {N.TypeDecl: "type", N.EnumDecl: "enum", N.AliasDecl: "alias", N.TraitDecl: "trait",
            N.ConstDecl: "const", N.TestDecl: "test", N.PropertyDecl: "property"}.get(type(d))


def name_of(d):
    return d.name


def doc_start(lines, line):
    """The first line of the `///` documentation right above a declaration (its own line without one)."""
    first = line
    while first > 1 and lines[first - 2].strip().startswith("///"):
        first -= 1
    return first


def items_of(loaded):
    """[(module, lines, [Item])] of the user modules: functions (also methods), types, traits, constants and tests."""
    out = []
    for m in user_modules(loaded):
        lines = source_lines(loaded, m.display)
        its = []
        for d in m.program.decls:
            k = kind_of(d)
            if k is None or (isinstance(d, N.FnDecl) and d.constructs) or \
                    (k == "test" and d.name.startswith("doc: ")):
                continue
            its.append(Item(d, m.display, lines))
        out.append((m.display, lines, its))
    return out


def context(loaded, name, max_tokens=DEFAULT_TOKENS):
    """The context of `name` as a dict (see `context_text`), or None when the program declares no such name."""
    mods = items_of(loaded)
    target, target_lines = None, None
    for _, lines, its in mods:
        for it in its:
            if it.name == name and it.kind not in ("test", "property"):
                target, target_lines = it, lines
                break
        if target is not None:
            break
    if target is None:
        return None
    defs = {}
    for _, _, its in mods:
        for it in its:
            if it.kind not in ("test", "property") and not (isinstance(it.d, N.FnDecl) and it.d.owner_kind) \
                    and it.name not in defs:
                defs[it.name] = it
    word_cache = {f: words("\n".join(lines)) for f, lines, _ in mods}
    own = {w for ln, w in word_cache[target.file] if target.first <= ln <= target.last}
    uses = [defs[w] for w in sorted(own) if w in defs and defs[w] is not target]
    tests, callers = [], []
    for f, lines, its in mods:
        for it in its:
            if it is target or it.d is target.d:
                continue
            hits = [ln for ln, w in word_cache[f] if w == target.word and it.line <= ln <= it.last]
            if not hits:
                continue
            if it.kind in ("test", "property"):
                tests.append((it, it.source(lines)))
            else:
                callers.append((it, hits[0], lines[hits[0] - 1].strip()))
    out = {"name": target.name, "kind": target.kind, "file": target.file, "line": target.line,
           "source": target.source(target_lines), "uses": [], "tests": [], "callers": [],
           "omitted": {"uses": 0, "tests": 0, "callers": 0}}
    budget = max_tokens * 4
    used = len(head_text(out)) + len(out["source"]) + 1
    for it in uses:
        entry = {"name": it.name, "kind": it.kind, "signature": it.signature, "file": it.file, "line": it.line}
        used = add(out, "uses", entry, use_text(entry), used, budget)
    for it, src in tests:
        entry = {"name": it.d.name, "kind": it.kind, "file": it.file, "line": it.line, "source": src}
        used = add(out, "tests", entry, test_text(entry), used, budget)
    for it, ln, code in callers:
        entry = {"name": it.name, "kind": it.kind, "signature": it.signature, "file": it.file, "line": ln,
                 "code": code}
        used = add(out, "callers", entry, caller_text(entry), used, budget)
    out["tokens"] = tokens_of(context_text(out, with_count=False))
    return out


def add(out, section, entry, text, used, budget):
    if used + len(text) + 1 > budget:
        out["omitted"][section] += 1
        return used
    out[section].append(entry)
    return used + len(text) + 1


def head_text(c):
    return f"{c['kind']} {c['name']} — {c['file']}:{c['line']}"


def use_text(e):
    return f"  {e['signature']}   // {e['file']}:{e['line']}"


def test_text(e):
    return f"  // {e['file']}:{e['line']}\n" + "\n".join("  " + x for x in e["source"].split("\n"))


def caller_text(e):
    return f"  {e['name']} — {e['file']}:{e['line']}: {e['code']}"


def context_text(c, with_count=True):
    out = [head_text(c), c["source"]]
    for section, fmt in (("uses", use_text), ("tests", test_text), ("callers", caller_text)):
        if c[section]:
            out.append("")
            out.append(f"{section}:")
            out.extend(fmt(e) for e in c[section])
    om = c["omitted"]
    if any(om.values()):
        parts = [f"{om[s]} {s}" for s in ("uses", "tests", "callers") if om[s]]
        out.append("")
        out.append(f"not shown: {', '.join(parts)} (raise --max-tokens)")
    if with_count:
        out.append("")
        out.append(f"~{c['tokens']} tokens")
    return "\n".join(out)
