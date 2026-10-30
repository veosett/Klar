"""Self-hosting check: the parts of the compiler written in Klar (compiler/*.klar) must behave exactly like
the Python implementation, on every .klar file of the repository and on error snippets:

* stage 3a, the lexer (compiler/lexer.klar): same tokens (kinds, values, spans, string parts) and the same
  errors (code, message, position) as klar/lexer.py;
* stage 3b, the parser (compiler/parser.klar): the same syntax tree (every node with all its spans) and the same
  syntax errors (with hints) as klar/parser.py;
* stage 4a/b, the checker, loader and safety analysis (compiler/checker.klar, loader.klar, safety.klar): the same
  diagnostics, and the same annotations (the type of every expression, the resolution and type arguments of every
  call) on every repository file and on the programs of tests/selfhost_cases.txt;
* stage 4c, the backend middle (compiler/lower.klar, own.klar, opt.klar, regalloc.klar): the same KIR, data image
  and register allocation for every program with a `main`, and for the test executable of every file with `test`
  blocks;
* stage 4d, the x86-64 emitter and the linkers (compiler/x64.klar, emit.klar, link.klar): byte-identical ELF and PE
  executables for every program with a `main`.

    python tests/selfhost.py                   # native builds of compiler/dump_*.klar (fast)
    python tests/selfhost.py lexer parser      # only some stages (lexer, parser, checker, lowering, emit)
    python tests/selfhost.py --interp checker  # run the Klar code in the reference interpreter (slow)
    python tests/selfhost.py --update          # regenerate compiler/builtin_sigs.klar and compiler/libsrc.klar
    python tests/selfhost.py -j 4              # at most 4 stages at a time (default: one per CPU)

The stages are independent and run in parallel processes; each prints its result with the time it took.
"""
import io
import json
import re
import shutil
import struct
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import fields

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from klar import nodes as N  # noqa: E402
from klar.diagnostics import KlarSyntaxError, Span  # noqa: E402
from klar.lexer import tokenize  # noqa: E402
from klar.parser import parse  # noqa: E402

ERROR_SNIPPETS = [
    "let x = a && b\n", "x || y\n", "i++\n", "a += 1\n", "Color::Red\n", "if !x {}\n", "f(x);\n", "let s = 'a'\n",
    "x & y\n", "x | y\n", "x ^ y\n", "~x\n", "x << 2\n", "x >> 2\n", "# comment\n", "@decorator\n", "`code`\n",
    "\"unterminated\n", "\"bad \\q escape\"\n", "\"open {interp\n", "\"{\"nested\"}\"\n", "\"{ }\"\n", "12px\n",
    "1.5e3\n", "3_000x\n", "let é = 1 ∑\n", "\"\\", "a;b\n", "0x\n", "0xfg\n", "0b102\n", "0o9\n", "1e\n", "1e+\n",
    "2.5E-3x\n", "0x1e-5\n",
]

PARSE_SNIPPETS = [
    "fn f() {\n  let x = " + " + ".join(["a"] * 150) + "\n}\n", "fn f() {\n  let x = " + " + ".join(["a"] * 300) + "\n}\n",
    "fn f() {\n  let x = a" + ".b()" * 300 + "\n}\n", "fn f() {\n  let x = " + "- " * 300 + "a\n}\n",
    "fn f() {\n  let x = " + "not " * 300 + "a\n}\n", "fn f() {\n  let x = " + " or ".join(["a"] * 300) + "\n}\n",
    "fn f() {\n  let x = " + " and ".join(["a * b"] * 300) + "\n}\n", "fn f() {\n  let x = " + " * ".join(["a"] * 300) + "\n}\n",
    "fn f() {\n  let x = a" + " with { b: 1 }" * 300 + "\n}\n",
    "fn f() {\n  if a {\n" + "  } else if a {\n" * 300 + "  }\n}\n",
    "fn f() {\n  let x\n}\n", "fn f() {\n  x.a = 1\n}\n", "fn f() {\n  1 = 2\n}\n", "fn f() {\n  a < b < c\n}\n",
    "fn f() {\n  let x = -1.abs()\n}\n", "fn f() {\n  let x = null\n}\n", "fn f() {\n  xs[0]\n}\n",
    "fn f() {\n  let t = (1, 2)\n}\n", "fn f() {\n  p.0\n}\n", "fn f() {\n  g(x = 1)\n}\n",
    "fn f() {\n  let x = if a { 1 }\n}\n", "fn f() {\n  fn g() {}\n}\n", "fn f() {\n  let g = fn(x) => { x }\n}\n",
    "fn f() {\n  match x {\n    1 -> 2\n  }\n}\n", "fn f() {\n  match x {}\n}\n",
    "fn f() {\n  match x {\n    Red => 1\n  }\n}\n", "fn f() {\n  match s {\n    \"a{b}\" => 1\n  }\n}\n",
    "fn f() {\n  let r = P { x 1 }\n}\n", "fn f() {\n  for x of xs {}\n}\n", "fn f() {\n  if x then {}\n}\n",
    "fn f() {\n  if x {} else y\n}\n", "fn f() {\n  a; b\n}\n", "fn f() {\n", "fn f() -> Int = 1\n",
    "fn f(): Int {}\n", "fn f(x) {}\n", "fn (x: Int) {}\n", "fn f[T](xs: List<T>) {}\n", "fn f<T>() {}\n",
    "fn f(self) {}\n", "fn f() uses {}\n", "let x = 1\n", "x + 1\n", "type P = { x: Int }\n", "type P x\n",
    "type P[T: Show] { x: T }\n", "enum E {\n  A(Int)\n}\n", "const N = 1\n", "const N: Int 1\n",
    "test name {}\n", "property \"p\" {}\n", "fn f() {}\nuse a.{b}\n", "use a\n", "use a.*\n", "use a.{}\n",
    "pub impl T for X {}\n", "pub test \"x\" {}\n", "trait T[A] {}\n", "trait T {\n  let x = 1\n}\n",
    "trait T {\n  fn m() -> Int\n}\n", "trait T {\n  fn m(self: Int) -> Int\n}\n", "trait T {\n  fn m[U](self) -> U {\n    return 1\n  }\n}\n",
    "impl[T] Show for X {}\n", "impl Show X {}\n", "impl Show for X {\n  fn show(self) -> Str\n}\n",
    "impl Show for X {\n  fn show[U](self) -> Str {\n    return \"\"\n  }\n}\n", "fn f() {} fn g() {}\n",
    "/// >>> let x = \n fn f() {}\n", "/// >>> 1 2\nfn f() {}\n", "module a.b x\n", "fn f() {\n  let s = \"{1 2}\"\n}\n",
    "fn f() {\n  return 1 2\n}\n", "fn f() {\n  let x = Map { 1 2 }\n}\n", "fn f() {\n  let x = [1, 2\n}\n",
    "fn f() {\n  g(1, 2\n}\n", "fn f() {\n  let x = fn(x) x\n}\n", "fn f() {\n  let x: (Int) = 1\n}\n",
    "fn f(x: fn(Int) Int) {}\n", "fn f() {\n  match x {\n    Some x => 1\n  }\n}\n",
    "fn f() {\n  match x {\n    E.A(1, => 1\n  }\n}\n", "fn f() {\n  match x {\n    + => 1\n  }\n}\n",
    "fn f() {\n  let x = * 2\n}\n", "fn f() {\n  let x = 0xff\n}\n",
    "type X = new Int\n  ensures value > 0\n", "type X = new\n", "type X = new Int requires\n",
    "type X[T] = new fn(T) -> Int\n  requires true\n\nfn f() {}\n", "impl[T: A + B, U] S for P[T, U] {\n}\n",
]

CASES = os.path.join(ROOT, "tests", "selfhost_cases.txt")


def check_cases():
    """The cases of tests/selfhost_cases.txt: [(name, {file name: source})], main.klar first."""
    cases, cur = [], None
    with open(CASES, encoding="utf-8") as f:
        lines = f.read().split("\n")
    for line in lines:
        if line.startswith("=== "):
            cur = (line[4:].strip(), {"main.klar": []}, ["main.klar"])
            cases.append(cur)
        elif line.startswith("--- ") and cur is not None:
            cur[2].append(line[4:].strip())
            cur[1][cur[2][-1]] = []
        elif cur is not None:
            cur[1][cur[2][-1]].append(line)
        # (lines before the first case are comments)
    return [(name, {f: "\n".join(ls).rstrip("\n") + "\n" for f, ls in files.items()}) for name, files, _ in cases]


def write_cases(d):
    paths = []
    for i, (name, files) in enumerate(check_cases()):
        folder = os.path.join(d, f"case{i}")
        os.makedirs(folder)
        for fname, text in files.items():
            os.makedirs(os.path.dirname(os.path.join(folder, fname)), exist_ok=True)
            with open(os.path.join(folder, fname), "w", encoding="utf-8") as f:
                f.write(text)
        paths.append(os.path.join(folder, "main.klar"))
    return paths


def klar_string(text):
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("{", "\\{").replace("}", "\\}") \
        .replace("\n", "\\n").replace("\t", "\\t") + '"'


def builtin_sigs_source():
    """compiler/builtin_sigs.klar: the built-in signatures of klar/builtins.py and klar/native/intrinsics.py, as
    Klar data (the Klar checker parses them with the Klar parser, like the Python checker does)."""
    from klar.builtins import FOREIGN_METHODS, FOREIGN_NOTES, GLOBALS, METHODS
    from klar import __version__
    from klar.diagnostics import CODES
    from klar.tools.runtools import AGENTS_TEMPLATE, LIB_TEMPLATE, MAIN_TEMPLATE
    from klar.native.intrinsics import SYS_SIGNATURES

    def str_list(items, indent="    "):
        return "[\n" + "".join(f"{indent}{klar_string(x)},\n" for x in items) + "  ]"

    def pairs(items):
        return "[\n" + "".join(f"    Pair {{ first: {klar_string(a)}, second: {klar_string(b)} }},\n"
                               for a, b in items) + "  ]"
    out = ["// Generated by `python tests/selfhost.py --update` from klar/builtins.py, klar/native/intrinsics.py,",
           "// klar/diagnostics.py (the error catalog), the version and the list of klar/rt/*.klar:",
           "// do not edit by hand (tests/selfhost.py fails when this file is out of date).", "",
           "/// Signatures of the built-in functions.",
           "pub fn global_sigs() -> List[Str] {", f"  return {str_list(s for s, _ in GLOBALS.values())}", "}", "",
           "/// Built-in methods: (receiver type, signature), in declaration order.",
           "pub fn method_sigs() -> List[Pair[Str, Str]] {",
           f"  return {pairs((o, s) for o, ms in METHODS.items() for s, _ in ms.values())}", "}", "",
           "/// Intrinsics of the runtime modules (klar/rt).",
           "pub fn sys_sigs() -> List[Str] {", f"  return {str_list(SYS_SIGNATURES)}", "}", "",
           "/// Method names from other languages and the Klar name (empty: no direct equivalent).",
           "pub fn foreign_methods() -> List[Pair[Str, Str]] {",
           f"  return {pairs((k, v or '') for k, v in FOREIGN_METHODS.items())}", "}", "",
           "pub fn foreign_notes() -> List[Pair[Str, Str]] {",
           f"  return {pairs(FOREIGN_NOTES.items())}", "}", "",
           "/// The error catalog of `klar explain`: (code, title, explanation).",
           "pub fn diag_codes() -> List[List[Str]] {",
           "  return [\n" + "".join(f"    [{klar_string(c)}, {klar_string(t)}, {klar_string(x)}],\n"
                                    for c, (t, x) in CODES.items()) + "  ]", "}", "",
           "/// The templates of `klar new` (Python str.format fields: {name}, {pkg}).",
           "pub fn main_template() -> Str {", f"  return {klar_string(MAIN_TEMPLATE)}", "}", "",
           "pub fn lib_template() -> Str {", f"  return {klar_string(LIB_TEMPLATE)}", "}", "",
           "pub fn agents_template() -> Str {", f"  return {klar_string(AGENTS_TEMPLATE)}", "}", "",
           "/// The version of Klar.",
           "pub fn klar_version() -> Str {", f"  return {klar_string(__version__)}", "}", "",
           "/// The files of the runtime (klar/rt), which form one module.",
           "pub fn rt_files() -> List[Str] {", f"  return {str_list(rt_files())}", "}", ""]
    return "\n".join(out)


def rt_files():
    return sorted(f for f in os.listdir(os.path.join(ROOT, "klar", "rt")) if f.endswith(".klar"))


def library_files():
    """The files of the library directory klarc needs (paths under klar/): the prelude, the runtime, the standard
    library, the reference of `klarc spec` and the template of `klarc view`."""
    lib = os.path.join(ROOT, "klar")
    out = ["ai_reference.md", "prelude.klar"]
    for sub in ("rt", "std"):
        out += [f"{sub}/{f}" for f in sorted(os.listdir(os.path.join(lib, sub))) if f.endswith(".klar")]
    return out + ["tools/view_template.html"]


def library_source():
    """compiler/libsrc.klar: the library files as Klar data, line by line — klarc reads them when the library
    directory is not on disk (compiler/libfs.klar), so a klarc binary works anywhere on its own."""
    out = ["// Generated by `python tests/selfhost.py --update` from klar/prelude.klar, klar/rt, klar/std,",
           "// klar/ai_reference.md and klar/tools/view_template.html: do not edit by hand (tests/selfhost.py fails when",
           "// this file is out of date). klarc reads these copies when the library directory is not on disk",
           "// (compiler/libfs.klar).", "",
           "/// The files built into klarc, by path under the library directory.",
           "pub fn embedded_paths() -> List[Str] {", "  return ["]
    files = library_files()
    out += [f"    {klar_string(f)}," for f in files]
    out += ["  ]", "}", "", "/// The lines of a library file built into klarc ([]: it is not one).",
            "pub fn embedded_lines(path: Str) -> List[Str] {", "  return match path {"]
    for f in files:
        with open(os.path.join(ROOT, "klar", f), encoding="utf-8", newline="") as fh:
            lines = fh.read().split("\n")
        out.append(f"    {klar_string(f)} => [")
        out += [f"      {klar_string(line)}," for line in lines]
        out.append("    ],")
    out += ["    _ => [],", "  }", "}", ""]
    return "\n".join(out)


BUILTIN_SIGS = os.path.join(ROOT, "compiler", "builtin_sigs.klar")
LIBSRC = os.path.join(ROOT, "compiler", "libsrc.klar")


def check_generated(path, want, update):
    try:
        with open(path, encoding="utf-8", newline="") as f:
            have = f.read()
    except OSError:
        have = None
    if have == want:
        return 0
    name = os.path.relpath(path, ROOT).replace(os.sep, "/")
    if update:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(want)
        print(f"updated {name}")
        return 0
    print(f"DIFF {name} is out of date: run `python tests/selfhost.py --update`")
    return 1


def check_builtin_sigs(update):
    return check_generated(BUILTIN_SIGS, builtin_sigs_source(), update) + \
        check_generated(LIBSRC, library_source(), update)


def klar_files():
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in ("node_modules", "build", "__pycache__"))
        for f in sorted(files):
            if f.endswith(".klar"):
                yield os.path.join(root, f)


def python_tokens(src):
    try:
        toks = tokenize(src, "x.klar")
    except KlarSyntaxError as ex:
        d = ex.diag
        return [{"error": d.code, "message": d.message, "hint": d.hint, "span": [d.span.line, d.span.col]}]
    out = []
    for t in toks:
        item = {"kind": t.kind, "value": "\n" if t.kind == "NEWLINE" else t.value,
                "span": [t.span.line, t.span.col, t.span.end_line, t.span.end_col]}
        if t.kind == "STR":
            item["parts"] = [p if isinstance(p, str) else list(p) for p in t.parts]
        out.append(item)
    return out


def python_tree(src):
    try:
        prog = parse(src, "x.klar")
    except KlarSyntaxError as ex:
        d = ex.diag
        return {"error": d.code, "message": d.message, "hint": d.hint, "span": [d.span.line, d.span.col]}
    return full_json(prog)


def full_json(n):
    """Like klar.nodes.to_json, but with every field (all the `*_span`s too) and without node ids."""
    if isinstance(n, N.Node):
        d = {"node": type(n).__name__, "span": full_json(n.span)}
        for f in fields(n):
            if f.name not in ("span", "file"):
                d[f.name] = full_json(getattr(n, f.name))
        return d
    if isinstance(n, Span):
        return [n.line, n.col, n.end_line, n.end_col]
    if isinstance(n, (list, tuple)):
        return [full_json(x) for x in n]
    if isinstance(n, dict):
        return {k: full_json(v) for k, v in n.items()}
    if isinstance(n, float):
        return ["float", struct.unpack("<q", struct.pack("<d", n))[0]]   # the bits: -0.0 and 0.0 differ
    return n


def first_difference(a, b, path="tree"):
    """Where two JSON trees first differ, for the report."""
    if isinstance(a, dict) and isinstance(b, dict):
        for k in list(a) + [k for k in b if k not in a]:
            if a.get(k) != b.get(k):
                return first_difference(a.get(k), b.get(k), f"{path}.{k}")
        return path, None, None
    if isinstance(a, list) and isinstance(b, list):
        for i, (x, y) in enumerate(zip(a, b)):
            if x != y:
                return first_difference(x, y, f"{path}[{i}]")
        return f"{path} (length)", len(a), len(b)
    return path, a, b


def run_driver(name, paths, interp):
    driver = os.path.join(ROOT, "compiler", name)
    cmd = [sys.executable, "-m", "klar", "run"] + (["--interp"] if interp else []) + [driver] + paths
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
    return proc.stdout


def klar_tokens(paths, interp):
    out = run_driver("dump_tokens.klar", paths, interp)
    result, cur = {}, None
    for line in out.splitlines():
        obj = json.loads(line)
        if set(obj) == {"file"}:
            cur = obj["file"]
            result[cur] = []
        else:
            result[cur].append(obj)
    return result


def klar_trees(paths, interp):
    out = run_driver("dump_ast.klar", paths, interp)
    result, cur = {}, None
    for line in out.splitlines():
        obj = json.loads(line)
        if set(obj) == {"file"}:
            cur = obj["file"]
        else:
            result[cur] = obj
    return result


def short(path):
    if path.startswith(ROOT):
        return os.path.relpath(path, ROOT)
    folder = os.path.basename(os.path.dirname(path))
    if folder.startswith("case"):
        return f"case `{check_cases()[int(folder[4:])][0]}`"
    return os.path.basename(path)


def write_snippets(d, prefix, snippets):
    paths = []
    for i, snippet in enumerate(snippets):
        p = os.path.join(d, f"{prefix}{i}.klar")
        with open(p, "w", encoding="utf-8") as f:
            f.write(snippet)
        paths.append(p)
    return paths


def check_lexer(files, interp):
    got = klar_tokens(files, interp)
    bad = tokens = 0
    for path in files:
        with open(path, encoding="utf-8") as f:
            want = python_tokens(f.read())
        have = got.get(path)
        tokens += len(want)
        if have != want:
            bad += 1
            first = next((k for k, (a, b) in enumerate(zip(want, have or [])) if a != b),
                         min(len(want), len(have or [])))
            print(f"DIFF {short(path)}: token {first}\n  python: {want[first] if first < len(want) else None}\n"
                  f"  klar:   {(have or [None] * (first + 1))[first] if have and first < len(have) else None}")
    print(f"lexer:  {len(files) - bad}/{len(files)} files identical ({tokens} tokens)")
    return bad


def count_nodes(x):
    if isinstance(x, dict):
        return ("node" in x) + sum(count_nodes(v) for v in x.values())
    if isinstance(x, list):
        return sum(count_nodes(v) for v in x)
    return 0


def check_parser(files, interp):
    got = klar_trees(files, interp)
    bad = nodes = errors = 0
    for path in files:
        with open(path, encoding="utf-8") as f:
            want = python_tree(f.read())
        have = got.get(path)
        nodes += count_nodes(want)
        errors += "error" in want
        if have != want:
            bad += 1
            where, a, b = first_difference(want, have)
            print(f"DIFF {short(path)}: {where}\n  python: {json.dumps(a)[:300]}\n  klar:   {json.dumps(b)[:300]}")
    print(f"parser: {len(files) - bad}/{len(files)} files identical ({nodes} nodes, {errors} syntax errors)")
    return bad


def python_diags(path):
    """The diagnostics of `klar check path` (checker and safety analysis) and the checker's annotations."""
    from klar.loader import load_path
    loaded = load_path(path)
    diags = sorted_diags({"severity": d.severity, "code": d.code, "message": d.message, "hint": d.hint,
                          "file": d.span.file, "span": [d.span.line, d.span.col]} for d in loaded.diags)
    return diags, annotations(loaded.program)


EXPRESSIONS = (N.IntLit, N.FloatLit, N.StrLit, N.BoolLit, N.UnitLit, N.ListLit, N.MapLit, N.Name, N.Unary, N.Binary,
               N.Call, N.MethodCall, N.FieldAccess, N.Try, N.RecordLit, N.WithExpr, N.Match, N.Lambda)


def annotations(program):
    """The static type of every expression and the resolution of every method call (by span), as recorded by the
    Python checker on the main module."""
    from klar.types import prune, show
    if program is None:
        return None
    types, resolved, calls, elems = {}, {}, {}, {}
    for n in N.walk(program):
        key = f"{n.span.file}:{n.span.line}:{n.span.col}:{n.span.end_line}:{n.span.end_col}"
        if isinstance(n, EXPRESSIONS) and getattr(n, "kt", None) is not None:
            types[key] = show(prune(n.kt))
        res = getattr(n, "resolved", None)
        if isinstance(n, N.MethodCall) and res:
            owner = res[1] if len(res) == 3 else ""
            resolved[key] = f"{res[0]} {owner} {res[-1] if len(res) > 1 else n.method}"
        if getattr(n, "sig", None) is not None and hasattr(n, "inst"):
            calls[key] = n.sig.name + " " + ",".join(f"{k}={show(prune(v))}" for k, v in n.inst.items())
        if isinstance(n, N.For) and getattr(n, "elem_kt", None) is not None:
            elems[key] = show(prune(n.elem_kt))
    return {"types": types, "resolved": resolved, "calls": calls, "elems": elems}


def sorted_diags(ds):
    return sorted(ds, key=lambda d: (d["file"], d["span"], d["code"], d["message"], d["severity"], d["hint"] or ""))


def klar_diags(paths, interp):
    out = run_driver("dump_check.klar", [os.path.join(ROOT, "klar")] + paths, interp)
    result, notes, cur = {}, {}, None
    for line in out.splitlines():
        obj = json.loads(line)
        if set(obj) == {"file"}:
            cur = obj["file"]
            result[cur] = []
            notes[cur] = None
        elif "types" in obj:
            notes[cur] = obj
        else:
            result[cur].append(obj)
    return {k: (sorted_diags(v), notes[k]) for k, v in result.items()}


def check_checker(files, interp):
    got = klar_diags(files, interp)
    bad = total = typed = 0
    for path in files:
        want, want_notes = python_diags(path)
        have, have_notes = got.get(path, (None, None))
        total += len(want)
        typed += len(want_notes["types"]) if want_notes else 0
        if have == want and have_notes != want_notes:
            bad += 1
            for table in ("types", "resolved", "calls", "elems"):
                w, h = (want_notes or {}).get(table, {}), (have_notes or {}).get(table, {})
                diff = sorted(k for k in set(w) | set(h) if w.get(k) != h.get(k))
                if diff:
                    k = diff[0]
                    print(f"DIFF {short(path)}: {len(diff)} {table} differ, e.g. at {k}: python {w.get(k)!r}, "
                          f"klar {h.get(k)!r}")
            continue
        if have != want:
            bad += 1
            first = next((k for k, (a, b) in enumerate(zip(want, have or [])) if a != b),
                         min(len(want), len(have or [])))
            print(f"DIFF {short(path)}: diagnostic {first} of {len(want)} (klar: {len(have or [])})\n"
                  f"  python: {want[first] if first < len(want) else None}\n"
                  f"  klar:   {have[first] if have and first < len(have) else None}")
    print(f"checker: {len(files) - bad}/{len(files)} files identical ({total} diagnostics, {typed} typed expressions)")
    return bad


def python_kir(path, tests=False):
    """The KIR and data image of klar/native/lower.py for a program (None if it has errors or is unsupported); with
    `tests`, of its test executable (the `test` blocks of the main module; None without any)."""
    from klar.loader import load_path
    from klar.native.link import Image
    from klar.native.lower import NativeUnsupported, lower_program
    loaded = load_path(path, with_runtime=True)
    if loaded.has_errors():
        return None
    img = Image()
    from klar.native.opt import inline_calls, optimize
    from klar.native.regalloc import allocate
    blocks = None
    if tests:
        blocks = [d for d in loaded.main.program.decls if isinstance(d, (N.TestDecl, N.PropertyDecl))]
        if not blocks:
            return None
    try:
        prog, _ = lower_program(loaded, img, blocks)
    except NativeUnsupported:
        return None
    out = {"fns": [[f.name, f.klar_name, f.nparams, f.nregs, [list(ins) for ins in f.code]] for f in prog.fns],
           "data": bytes(img.data).hex(), "syms": dict(img.data_syms), "abs": [list(a) for a in img.data_abs],
           "bss": dict(img.bss_syms), "bss_size": img.bss_size}
    # the backend's next steps, as `klar build` runs them: inlining, then per function optimization and allocation
    inline_calls(prog.fns)
    optimized = []
    for f in prog.fns:
        optimize(f)
        loc, used, xloc = allocate(f)
        optimized.append([f.name, f.nregs, f._labels, [list(ins) for ins in f.code],
                          {str(k): v for k, v in loc.items()}, list(used), {str(k): v for k, v in xloc.items()},
                          {str(k): sorted(v) for k, v in f.call_saves.items()}])
    out["optimized"] = optimized
    return out


def lowering_files():
    """The programs both lowerings compile: every repository file with a `main`."""
    out = []
    for path in klar_files():
        with open(path, encoding="utf-8") as f:
            if "\nfn main(" in "\n" + f.read():
                out.append(path)
    return out


def check_lowering(interp, tests=False):
    files = lowering_files() if not tests else list(klar_files())
    want = {p: python_kir(p, tests) for p in files}
    files = [p for p in files if want[p] is not None]
    out = run_driver("dump_kir.klar", [os.path.join(ROOT, "klar")] + (["+tests"] if tests else []) + files, interp)
    got, cur = {}, None
    for line in out.splitlines():
        obj = json.loads(line)
        if set(obj) == {"file"}:
            cur = obj["file"]
        else:
            got[cur] = obj
    bad = n_ins = 0
    for path in files:
        w, h = want[path], got.get(path)
        n_ins += sum(len(f[4]) for f in w["fns"]) + sum(len(f[3]) for f in w["optimized"])
        if h == w:
            continue
        bad += 1
        if h is None or "fns" not in h:
            print(f"DIFF {short(path)}: klar produced {h if h is None else list(h)}")
            continue
        wf = {f[0]: f for f in w["fns"]}
        hf = {f[0]: f for f in h["fns"]}
        names_w, names_h = [f[0] for f in w["fns"]], [f[0] for f in h["fns"]]
        if names_w != names_h:
            k = next((i for i, (a, b) in enumerate(zip(names_w, names_h)) if a != b), min(len(names_w), len(names_h)))
            print(f"DIFF {short(path)}: function #{k}: python {names_w[k:k + 3]}, klar {names_h[k:k + 3]}")
            continue
        for name in names_w:
            a, b = wf[name], hf[name]
            if a != b:
                if a[:4] != b[:4]:
                    print(f"DIFF {short(path)}: {name}: header python {a[:4]}, klar {b[:4]}")
                else:
                    k = next((i for i, (x, y) in enumerate(zip(a[4], b[4])) if x != y), min(len(a[4]), len(b[4])))
                    print(f"DIFF {short(path)}: {name} instruction {k}: python {a[4][k:k + 2]}, klar {b[4][k:k + 2]}")
                break
        else:
            for part in ("data", "syms", "abs", "bss", "bss_size"):
                if w[part] != h[part]:
                    print(f"DIFF {short(path)}: {part} differs")
                    break
            else:
                for a, b in zip(w["optimized"], h["optimized"]):
                    if a != b:
                        what = ["name", "nregs", "labels", "code", "loc", "used", "xloc", "call_saves"]
                        k = next(i for i in range(8) if a[i] != b[i])
                        if what[k] == "code":
                            j = next((i for i, (x, y) in enumerate(zip(a[3], b[3])) if x != y), min(len(a[3]), len(b[3])))
                            print(f"DIFF {short(path)}: optimized {a[0]} instruction {j}: python {a[3][j:j + 2]}, "
                                  f"klar {b[3][j:j + 2]}")
                        elif what[k] in ("loc", "xloc", "call_saves"):
                            dk = sorted(set(a[k]) | set(b[k]), key=int)
                            x = next(v for v in dk if a[k].get(v) != b[k].get(v))
                            print(f"DIFF {short(path)}: {what[k]} of {a[0]} at {x}: python {a[k].get(x)}, klar {b[k].get(x)}")
                        else:
                            print(f"DIFF {short(path)}: {what[k]} of {a[0]}: python {a[k]}, klar {b[k]}")
                        break
    what = "test executables" if tests else "programs"
    print(f"lowering: {len(files) - bad}/{len(files)} {what} identical ({n_ins} KIR instructions)")
    return bad


TARGETS = (("linux", "elf"), ("windows", "exe"), ("linux-arm64", "a64"), ("macos", "macho"))


def check_emit(interp, part=0, parts=1):
    """Executables built by the Klar backend (compiler/dump_exe.klar) == executables built by `klar build`."""
    from klar.native.build import build
    from klar.native.lower import NativeUnsupported
    files = lowering_files()[part::parts]
    bad = n_bytes = 0
    with tempfile.TemporaryDirectory() as d:
        want = {}
        for k, path in enumerate(files):
            try:
                for target, ext in TARGETS:
                    build(path, out=os.path.join(d, f"py{k}.{ext}"), target=target)
                want[path] = k
            except (NativeUnsupported, SystemExit):
                pass
        files = [p for p in files if p in want]
        got = {}
        for i in range(0, len(files), 8):     # in parts: one process for all files needs more memory than CI has
            os.makedirs(os.path.join(d, f"k{i}"))
            out = run_driver("dump_exe.klar", [os.path.join(ROOT, "klar"), os.path.join(d, f"k{i}")] + files[i:i + 8],
                             interp)
            got.update({k: os.path.join(f"k{i}", v) if v != "error" else v
                        for k, v in (line.split("\t") for line in out.splitlines())})
        for path in files:
            for _, ext in TARGETS:
                with open(os.path.join(d, f"py{want[path]}.{ext}"), "rb") as f:
                    w = f.read()
                n_bytes += len(w)
                h = None
                if path in got and got[path] != "error":
                    with open(os.path.join(d, f"{got[path]}.{ext}"), "rb") as f:
                        h = f.read()
                if h != w:
                    bad += 1
                    if h is None:
                        print(f"DIFF {short(path)}.{ext}: klar built nothing")
                    else:
                        k = next((i for i, (x, y) in enumerate(zip(w, h)) if x != y), min(len(w), len(h)))
                        print(f"DIFF {short(path)}.{ext}: first difference at byte {k:#x} (python {len(w)} bytes, "
                              f"klar {len(h)} bytes)")
    n = len(TARGETS) * len(files)
    label = f" ({part + 1}/{parts})" if parts > 1 else ""
    print(f"emit{label}: {n - bad}/{n} executables identical ({n_bytes} bytes)")
    return bad


def messy_variants(files, d):
    """Badly laid out copies of the files (deterministic): the formatter must undo the damage in the same way."""
    import random
    rnd = random.Random(7)
    out = []
    for k, path in enumerate(files):
        with open(path, encoding="utf-8", newline="") as f:
            src = f.read()
        lines = []
        for line in src.split("\n"):
            line = line.strip() if rnd.random() < 0.7 else "    " * rnd.randint(0, 3) + line.strip()
            if '"' not in line and "//" not in line:
                r = rnd.random()
                if r < 0.3:
                    line = line.replace(", ", ",")
                elif r < 0.5:
                    line = line.replace(" = ", "=").replace(" + ", "+")
                elif r < 0.6:
                    line = line.replace("(", "( ").replace(")", " )")
            lines.append(line + (" " if rnd.random() < 0.1 else ""))
            if rnd.random() < 0.05:
                lines.append("")
        p = os.path.join(d, f"messy{k}.klar")
        with open(p, "w", encoding="utf-8", newline="") as f:
            f.write(("\r\n" if k % 5 == 0 else "\n").join(lines))
        out.append(p)
    return out


def check_fmt(files, interp):
    """`klar fmt` written in Klar (compiler/fmt.klar) == klar/tools/fmt.py: the text, or the same refusal."""
    from klar.tools.fmt import FormatError, format_checked
    bad = 0
    with tempfile.TemporaryDirectory() as d:
        run_driver("dump_fmt.klar", [d] + files, interp)
        for k, path in enumerate(files):
            with open(path, encoding="utf-8", newline="") as f:
                src = f.read()
            try:
                want = format_checked(src)
            except FormatError as ex:
                want = "!" + str(ex)
            out = os.path.join(d, f"{k}.fmt")
            got = None
            if os.path.exists(out):
                with open(out, encoding="utf-8", newline="") as f:
                    got = f.read()
            if got != want:
                bad += 1
                print(f"DIFF fmt {short(path)}: {(got or '')[:120]!r} / {want[:120]!r}")
    print(f"fmt: {len(files) - bad}/{len(files)} files formatted identically")
    return bad


def python_report(path):
    """What `klar check path` prints (without the final "ok" line)."""
    from klar.cli import print_diags, user_diags
    from klar.loader import load_path
    loaded = load_path(path)
    out = io.StringIO()
    print_diags(loaded, user_diags(loaded), out)
    return out.getvalue()


def python_check_json(path):
    """What `klar check --json path` prints (without the final newline)."""
    from klar.cli import user_diags
    from klar.loader import load_path
    loaded = load_path(path)
    return json.dumps({"ok": not loaded.has_errors(), "diagnostics": [d.to_dict() for d in user_diags(loaded)]},
                      ensure_ascii=False, indent=2)


def check_report(files, interp):
    """The report of `klar check` rendered by the Klar compiler (compiler/report.klar) == klar/cli.py's: every
    diagnostic in the same order, with the same code frame, notes, hint and fix."""
    out = run_driver("dump_report.klar", [os.path.join(ROOT, "klar")] + files, interp)
    got = out.split("\0\n")
    bad = 0
    for k, path in enumerate(files):
        want = python_report(path)
        have = got[2 * k] if 2 * k < len(got) else None
        want_json = python_check_json(path)
        have_json = got[2 * k + 1] if 2 * k + 1 < len(got) else None
        if have == want and have_json != want_json:
            bad += 1
            print(f"DIFF report {short(path)} (--json):\n  python: {want_json[:300]!r}\n  klar:   {(have_json or '')[:300]!r}")
            continue
        if have != want:
            bad += 1
            if have is None:
                print(f"DIFF report {short(path)}: klar printed nothing")
                continue
            wl, hl = want.split("\n"), have.split("\n")
            i = next((i for i, (x, y) in enumerate(zip(wl, hl)) if x != y), min(len(wl), len(hl)))
            print(f"DIFF report {short(path)}: line {i + 1}\n  python: {wl[i] if i < len(wl) else None!r}\n"
                  f"  klar:   {hl[i] if i < len(hl) else None!r}")
    print(f"report: {len(files) - bad}/{len(files)} reports identical")
    return bad


def tree(folder):
    out = {}
    for root, _, files in os.walk(folder):
        for f in files:
            with open(os.path.join(root, f), "rb") as fh:
                out[os.path.relpath(os.path.join(root, f), folder)] = fh.read()
    return out


def check_new(klarc, d):
    """`klarc new` == `klar new`: the same messages and the same files."""
    from contextlib import redirect_stderr, redirect_stdout
    from klar.cli import main as cli_main
    py_dir, k_dir = os.path.join(d, "new_py"), os.path.join(d, "new_k")
    os.makedirs(py_dir)
    os.makedirs(k_dir)
    bad = 0
    old = os.getcwd()
    for args in (["My-App"], ["123x", "--lib"], ["a/b/c"], ["_x_"], ["My-App"]):
        out = io.StringIO()
        os.chdir(py_dir)
        try:
            with redirect_stdout(out), redirect_stderr(out):
                code = cli_main(["new"] + args)
        finally:
            os.chdir(old)
        proc = subprocess.run([klarc, "new"] + args, capture_output=True, text=True, cwd=k_dir)
        if (proc.stdout + proc.stderr, proc.returncode) != (out.getvalue(), code):
            bad += 1
            print(f"DIFF new {args}: {proc.stdout + proc.stderr!r} / {out.getvalue()!r}")
    if tree(py_dir) != tree(k_dir):
        bad += 1
        print("DIFF new: the projects differ")
    print(f"new: {'identical' if not bad else 'DIFFERENT'}")
    return bad


def names_of(path):
    """Names to look up in a file: its declarations, parameters, variables, fields and variants (at most 12)."""
    from klar.loader import load_path
    from klar.safety import iter_nodes
    loaded = load_path(path)
    if loaded.program is None:
        return []
    out = []
    for n in iter_nodes(loaded.program):
        name = getattr(n, "name", None) or getattr(n, "var", None) or getattr(n, "method", None)
        if isinstance(name, str) and "." not in name and name not in out:
            out.append(name)
    return out[:12]


def cli_output(argv, cwd=None):
    from contextlib import redirect_stderr, redirect_stdout
    from klar.cli import main as cli_main
    out, err = io.StringIO(), io.StringIO()
    old = os.getcwd()
    if cwd:
        os.chdir(cwd)
    try:
        with redirect_stdout(out), redirect_stderr(err):
            code = cli_main(argv)
    finally:
        os.chdir(old)
    return out.getvalue(), err.getvalue(), code


def check_inspect(klarc, files, label=""):
    """`klarc outline`, `klarc refs` and `klarc context` == the Python commands (text and --json) on every file, for
    the names declared and used in it."""
    import klar.tools.commands as commands
    from klar.loader import load_path
    bad = runs = 0
    lib = os.path.join(ROOT, "klar")
    original = commands.load_path
    for path in files:
        loaded = load_path(path)
        commands.load_path = lambda p, *a, **k: loaded if p == path else original(p, *a, **k)
        jobs = [["outline", path], ["outline", path, "--json"], ["outline", path, "--all"]]
        jobs += [["doc", q, "--in", path] for q in names_of(path)[:2]]
        big = len(loaded.sources.get(loaded.main.display, "").split("\n")) > 1500 if loaded.main else False
        for name in names_of(path)[:4 if big else 12]:
            jobs += [["refs", path, name], ["refs", path, name, "--json"]]
        for name in names_of(path)[:2 if big else 6]:
            jobs += [["context", path, name], ["context", path, name, "--json", "--max-tokens", "150"]]
        jobs += [["context", path, "no_such_name"], ["context", path, "no_such_name", "--json"]]
        for job in jobs:
            runs += 1
            want = cli_output(job)
            proc = subprocess.run([klarc] + job + ["--lib", lib], capture_output=True, text=True, encoding="utf-8")
            if (proc.stdout, proc.stderr, proc.returncode) != want:
                bad += 1
                if bad <= 10:
                    wl, hl = want[0].split("\n"), proc.stdout.split("\n")
                    i = next((i for i, (x, y) in enumerate(zip(wl, hl)) if x != y), min(len(wl), len(hl)))
                    print(f"DIFF {' '.join(job[:1] + [short(path)] + job[2:])}: line {i + 1}\n"
                          f"  python: {wl[i] if i < len(wl) else None!r} {want[1][:200]!r}\n"
                          f"  klar:   {hl[i] if i < len(hl) else None!r} {proc.stderr[:200]!r}")
    commands.load_path = original
    print(f"inspect{label}: {runs - bad}/{runs} outputs identical")
    return bad


def check_fmt_cli(klarc, d):
    """`klarc fmt` == `klar fmt` as commands: --diff, --check, --json and in-place formatting of damaged files."""
    import shutil
    files = [p for p in klar_files() if os.sep + "rt" + os.sep not in p][:60]
    src_dir = os.path.join(d, "fmt_src")
    os.makedirs(src_dir, exist_ok=True)
    messy_variants(files, src_dir)
    bad = 0
    for flags in (["--diff"], ["--check"], ["--json"], []):
        py_dir, k_dir = os.path.join(d, "fmt_py"), os.path.join(d, "fmt_k")
        for x in (py_dir, k_dir):
            shutil.rmtree(x, ignore_errors=True)
            shutil.copytree(src_dir, x)
        want = cli_output(["fmt", "."] + flags, cwd=py_dir)
        proc = subprocess.run([klarc, "fmt", "."] + flags, capture_output=True, text=True, encoding="utf-8", cwd=k_dir)
        if (proc.stdout, proc.stderr, proc.returncode) != want or tree(py_dir) != tree(k_dir):
            bad += 1
            print(f"DIFF fmt {flags}: exit {want[2]}/{proc.returncode}, output {proc.stdout == want[0]}, "
                  f"errors {proc.stderr == want[1]}, files {tree(py_dir) == tree(k_dir)}")
    print(f"fmt (command): {'identical' if not bad else 'DIFFERENT'}")
    return bad


def check_patch(klarc, files):
    """`klarc patch` == `klar patch` (--dry-run, text and --json): deletions, renames, node edits and unknown targets
    on repository files."""
    import json
    from klar.parser import parse
    from klar.tools.patch import decl_targets
    bad = runs = 0
    lib = os.path.join(ROOT, "klar")
    for path in files:
        with open(path, encoding="utf-8") as f:
            src = f.read()
        try:
            targets = list(decl_targets(parse(src, os.path.basename(path))))
        except Exception:
            continue
        if not targets:
            continue
        fns = [t for t in targets if t.isidentifier() and t[0].islower()]
        patches = [[{"delete": targets[0]}], [{"delete": targets[-1]}], [{"replace": targets[0][:-1] + "q", "with": ""}],
                   [{"id": 7, "with": "x"}], [{"insert": "fn zz_added() -> Int {\n  return 1\n}", "after": targets[-1]}]]
        if fns:
            patches.append([{"rename": fns[0], "to": fns[0] + "_x"}])
            patches.append([{"replace": fns[0], "with": "fn " + fns[0] + "() {}"}, {"rename": fns[-1], "to": "zz"}])
        for edits in patches:
            for flags in (["--dry-run", "--json"], ["--dry-run"]):
                runs += 1
                job = ["patch", path, json.dumps({"edits": edits})] + flags
                want = cli_output(job)
                proc = subprocess.run([klarc] + job + ["--lib", lib], capture_output=True, text=True, encoding="utf-8")
                if (proc.stdout, proc.stderr, proc.returncode) != want:
                    bad += 1
                    if bad <= 10:
                        print(f"DIFF patch {short(path)} {job[2]} {flags}: exit {want[2]}/{proc.returncode}\n"
                              f"  python: {want[0][:300]!r} {want[1][:200]!r}\n"
                              f"  klar:   {proc.stdout[:300]!r} {proc.stderr[:200]!r}")
    print(f"patch: {runs - bad}/{runs} outputs identical")
    return bad


def check_dev(klarc):
    """`klarc dev` == `klar dev` (text and --json) and `klarc test` == `klar test` on the examples and native test
    programs (properties included)."""
    import glob
    bad = runs = 0
    lib = os.path.join(ROOT, "klar")
    files = sorted(glob.glob(os.path.join(ROOT, "examples", "*.klar")) +
                   glob.glob(os.path.join(ROOT, "tests", "native", "*.klar")))
    for path in files:
        for job in (["dev", path, "--json"], ["dev", path], ["test", path], ["test", path, "--seed", "5", "-q"]):
            runs += 1
            want = cli_output(job)
            proc = subprocess.run([klarc] + job + ["--lib", lib], capture_output=True, text=True, encoding="utf-8",
                                  stdin=subprocess.DEVNULL)
            if (proc.stdout, proc.returncode) != (want[0], want[2]):
                bad += 1
                if bad <= 10:
                    print(f"DIFF {job[0]} {short(path)} {job[2:]}: exit {want[2]}/{proc.returncode}\n"
                          f"  python: {want[0][:300]!r}\n  klar:   {proc.stdout[:300]!r} {proc.stderr[:200]!r}")
    print(f"dev and test: {runs - bad}/{runs} outputs identical")
    return bad


PKG_STEPS = ["deps", "add geo --path ../geo", "deps", "deps --json", "add json5 --git REPO --tag v1", "fetch --json",
             "update", "update json5 --json", "add json5 --git REPO", "remove geo", "remove nothere", "add Bad --path x",
             "add x", "add y --path ../a --git z", "add y --path ../a --tag v1", "add y --git REPO --tag a --rev b",
             "add ghost --path ../ghost --no-fetch", "fetch", "remove ghost --json", "deps"]


def pkg_project(d):
    """A project with a path dependency (which has its own) and a local git repository with a tag."""
    for name, toml in (("app", '[package]\nname = "app"\nversion = "0.1.0"\n'),
                       ("geo", '[package]\nname = "geo"\n\n[dependencies]\nmathx = { path = "../mathx" }\n'),
                       ("mathx", '[package]\nname = "mathx"\n'), ("repo", '[package]\nname = "json5"\n')):
        os.makedirs(os.path.join(d, name))
        with open(os.path.join(d, name, "klar.toml"), "w", encoding="utf-8", newline="\n") as f:
            f.write(toml)
    repo = os.path.join(d, "repo")
    env = dict(os.environ, GIT_AUTHOR_DATE="2026-01-01T00:00:00", GIT_COMMITTER_DATE="2026-01-01T00:00:00")
    for cmd in (["init", "-q"], ["add", "."], ["-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", "one"],
                ["tag", "v1"]):
        subprocess.run(["git"] + cmd, cwd=repo, check=True, env=env)
    with open(os.path.join(repo, "lib.klar"), "w") as f:
        f.write("// two\n")
    for cmd in (["add", "."], ["-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", "two"]):
        subprocess.run(["git"] + cmd, cwd=repo, check=True, env=env)


def project_state(app):
    out = []
    for name in ("klar.toml", "klar.lock"):
        p = os.path.join(app, name)
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                out.append(f.read())
    deps = os.path.join(app, ".klar", "deps")
    out.append(sorted(os.listdir(deps)) if os.path.isdir(deps) else [])
    return out


def check_pkg(klarc, d):
    """`klarc add/remove/fetch/update/deps` == the Python commands: the same output, klar.toml, klar.lock and fetched
    packages after each step of a scenario with path and git dependencies."""
    import shutil
    if shutil.which("git") is None:
        print("packages: skipped (no git)")
        return 0
    sides = {k: os.path.join(d, "pkg_" + k) for k in ("py", "k")}
    for side in sides.values():
        pkg_project(side)
    bad = 0
    for step in PKG_STEPS:
        got = {}
        for k, side in sides.items():
            app = os.path.join(side, "app")
            job = step.replace("REPO", os.path.join(side, "repo")).split()
            if k == "py":
                out, err, code = cli_output(job, cwd=app)
            else:
                proc = subprocess.run([klarc] + job, capture_output=True, text=True, encoding="utf-8", cwd=app)
                out, err, code = proc.stdout, proc.stderr, proc.returncode
            got[k] = [(out + err).replace(side, "ROOT"), code] + [str(x).replace(side, "ROOT") for x in project_state(app)]
        if got["py"] != got["k"]:
            bad += 1
            print(f"DIFF packages `{step}`:\n  python: {got['py']!r:.400}\n  klar:   {got['k']!r:.400}")
    print(f"packages: {len(PKG_STEPS) - bad}/{len(PKG_STEPS)} steps identical")
    return bad


EVAL_CASES = [["1 + 2"], ["let x = [1, 2]", "x.map(fn(v) => v * 2)"], ['"a,b".split(",")'], ['print("hi")', "42"],
              ["nope(1)"], ['let x: Int = "s"', "x"], ["Some(3)"], ['Map {}.set("a", 1)'], ["[1, 2].get_or(5, 0) + 1.5"],
              ["2.5 * 2.0"], ['"é".len()'], ["let xs = [3, 1, 2]", "xs.sort()"], ["[1].get_or(0, 0) / 0"],
              ['let n = "x".to_int().ok_or("bad")', "n"], ['print("before")', "assert 1 == 2", "1"], ["sq(4)"],
              ['file_exists("/no/such/file")'], ['read_file("/no/such/file").is_err()'], ["current_dir().len() > 0"],
              ["now_ms() > 0"], ["random_int(1, 1)"], ["cli_args().len()"], ['run_capture(["true"], "", "")']]


def check_sandbox(klarc, d):
    """`klarc run --allow` == `klar run --allow`: the same output, R0016 messages and exit codes for every right."""
    sys.path.insert(0, os.path.join(ROOT, "tests"))
    from test_klar import Sandbox
    work = os.path.join(d, "sandbox")
    os.makedirs(os.path.join(work, "data"), exist_ok=True)
    for name, text in (("data/a.txt", "hi"), ("other.txt", "secret"), ("p.klar", Sandbox.SRC)):
        with open(os.path.join(work, name), "w", encoding="utf-8") as f:
            f.write(text)
    bad = runs = 0
    lib = os.path.join(ROOT, "klar")
    for step, allow in Sandbox.CASES + [("read", "fs,disk")]:
        runs += 1
        want = subprocess.run([sys.executable, "-m", "klar", "run", "-q", "--allow", allow, "p.klar", step],
                              capture_output=True, text=True, cwd=work, env=dict(os.environ, PYTHONPATH=ROOT))
        got = subprocess.run([klarc, "run", "p.klar", "--allow", allow, "--lib", lib, "--", step], capture_output=True,
                             text=True, cwd=work)
        if (want.stdout, want.stderr, want.returncode) != (got.stdout, got.stderr, got.returncode):
            bad += 1
            if bad <= 5:
                print(f"DIFF run --allow {allow!r} {step}:\n  python: {want.stdout!r} {want.stderr[:300]!r} "
                      f"{want.returncode}\n  klar:   {got.stdout!r} {got.stderr[:300]!r} {got.returncode}")
    print(f"sandbox: {runs - bad}/{runs} runs identical")
    return bad


def check_spec_full(klarc):
    """`klarc spec --full` == `klar spec --full` (`klar_spec` in check_mcp covers the short one)."""
    want = subprocess.run([sys.executable, "-m", "klar", "spec", "--full"], capture_output=True, text=True, cwd=ROOT,
                          env=dict(os.environ, PYTHONPATH=ROOT))
    got = subprocess.run([klarc, "spec", "--full", "--lib", os.path.join(ROOT, "klar")], capture_output=True, text=True,
                         cwd=ROOT)
    bad = int((want.stdout, want.returncode) != (got.stdout, got.returncode))
    print(f"spec --full: {'different' if bad else 'identical'}")
    return bad


def check_limit(klarc, d):
    """`--timeout`: klarc builds the bytes klar builds, and `run` and `test` stop the same way with R0018."""
    work = os.path.join(d, "limit")
    os.makedirs(work, exist_ok=True)
    shutil.copy(os.path.join(ROOT, "tests", "limits", "endless.klar"), os.path.join(work, "p.klar"))
    env = dict(os.environ, PYTHONPATH=ROOT)
    lib = ["--lib", os.path.join(ROOT, "klar")]
    subprocess.run([sys.executable, "-m", "klar", "build", "p.klar", "-o", "a", "--timeout", "1"], cwd=work, env=env,
                   check=True, capture_output=True)
    subprocess.run([klarc, "build", "p.klar", "-o", "b", "--timeout", "1"] + lib, cwd=work, check=True, capture_output=True)
    with open(os.path.join(work, "a"), "rb") as a, open(os.path.join(work, "b"), "rb") as b:
        bad = int(a.read() != b.read())
    if bad:
        print("DIFF build --timeout: the executables differ")
    jobs = ((["run", "--timeout", "1", "p.klar"], ["run", "p.klar", "--timeout", "1"] + lib),
            (["run", "--timeout", "1", "p.klar", "fib"], ["run", "p.klar", "--timeout", "1"] + lib + ["--", "fib"]),
            (["test", "p.klar", "--timeout", "1"], ["test", "p.klar", "--timeout", "1"] + lib))

    def shown(proc):            # where the recursion was when the time ran out depends on the machine
        return [re.sub(r"(?m)^.*call stack.*$", "", s) for s in (proc.stdout, proc.stderr)] + [proc.returncode]
    for py_args, klarc_args in jobs:
        want = shown(subprocess.run([sys.executable, "-m", "klar"] + py_args, capture_output=True, text=True, cwd=work,
                                    env=env))
        got = shown(subprocess.run([klarc] + klarc_args, capture_output=True, text=True, cwd=work))
        if want != got or "R0018" not in want[0] + want[1]:
            bad += 1
            print(f"DIFF {' '.join(py_args)}:\n  python: {want!r}\n  klar:   {got!r}")
    print(f"limit: {1 + len(jobs) - bad}/{1 + len(jobs)} identical")
    return bad


def check_eval(klarc, d):
    """`klarc eval` == `klar eval` (text and --json, alone and --in a file)."""
    ctx = os.path.join(d, "ctx.klar")
    with open(ctx, "w", encoding="utf-8") as f:
        f.write("fn sq(n: Int) -> Int {\n  return n * n\n}\n\nfn main() uses io {\n  print(sq(3))\n}\n\n"
                "test \"t\" {\n  assert sq(2) == 4\n}\n")
    bad = runs = 0
    for case in EVAL_CASES:
        for extra in ([], ["--in", ctx]):
            for flags in ([], ["--json"]):
                runs += 1
                job = ["eval"] + case + extra + flags
                want = cli_output(job, cwd=d)
                proc = subprocess.run([klarc] + job + ["--lib", os.path.join(ROOT, "klar")], capture_output=True,
                                      text=True, encoding="utf-8", cwd=d)
                if (proc.stdout, proc.stderr, proc.returncode) != want:
                    bad += 1
                    print(f"DIFF eval {case} {extra} {flags}:\n  python: {want!r:.300}\n"
                          f"  klar:   {(proc.stdout, proc.stderr, proc.returncode)!r:.300}")
    print(f"eval: {runs - bad}/{runs} outputs identical")
    return bad


def check_view(klarc, d):
    """`klarc view` == `klar view`: the --json data and the HTML page, on the examples, native tests, benchmarks, std
    and compiler files."""
    import glob
    files = sorted(glob.glob(os.path.join(ROOT, "examples", "*.klar")) +
                   glob.glob(os.path.join(ROOT, "tests", "native", "*.klar")) +
                   glob.glob(os.path.join(ROOT, "bench", "programs", "*", "*.klar")) +
                   glob.glob(os.path.join(ROOT, "klar", "std", "*.klar")) +
                   glob.glob(os.path.join(ROOT, "compiler", "*.klar")))
    bad = runs = 0
    lib = os.path.join(ROOT, "klar")
    for k, path in enumerate(files):
        runs += 1
        want = cli_output(["view", path, "--json"])
        proc = subprocess.run([klarc, "view", path, "--json", "--lib", lib], capture_output=True, text=True,
                              encoding="utf-8")
        same = (proc.stdout, proc.returncode) == (want[0], want[2])
        if same and k % 8 == 0:
            pages = [os.path.join(d, f"view_{side}.html") for side in ("py", "k")]
            cli_output(["view", path, "-o", pages[0]])
            subprocess.run([klarc, "view", path, "-o", pages[1], "--lib", lib], capture_output=True)
            same = tree_file(pages[0]) == tree_file(pages[1])
        if not same:
            bad += 1
            print(f"DIFF view {short(path)}: exit {want[2]}/{proc.returncode}")
    print(f"view: {runs - bad}/{runs} outputs identical")
    return bad


def tree_file(path):
    with open(path, "rb") as f:
        return f.read()


def lsp_frame(msg):
    data = json.dumps(msg).encode()
    return b"Content-Length: %d\r\n\r\n" % len(data) + data


def lsp_messages(out):
    msgs, i = [], 0
    while i < len(out):
        j = out.index(b"\r\n\r\n", i)
        n = int(re.search(rb"Content-Length: (\d+)", out[i:j]).group(1))
        msgs.append(json.loads(out[j + 4:j + 4 + n]))
        i = j + 4 + n
    return msgs


def lsp_session(path, limit):
    """Requests at the identifiers of a file (hover, definition, references, rename, signature help, completion),
    then symbols, formatting, a rename, a broken edit and the shutdown."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    uri = "file://" + os.path.abspath(path).replace(os.sep, "/")
    td = {"uri": uri}
    reqs = [{"id": 1, "method": "initialize", "params": {}}, {"method": "initialized", "params": {}},
            {"method": "textDocument/didOpen", "params": {"textDocument": {"uri": uri, "text": text}}}]
    positions = []
    for ln, line in enumerate(text.split("\n")):
        for m in re.finditer(r"[A-Za-z_][A-Za-z0-9_]*", line):
            positions += [(ln, m.start()), (ln, m.end() - 1)]
        for c in "(.":
            if c in line:
                positions.append((ln, line.index(c) + 1))
    positions = positions[::max(1, len(positions) // limit)][:limit]
    k = 2
    for ln, col in positions:
        for meth in ("hover", "definition", "references", "prepareRename", "signatureHelp", "completion"):
            reqs.append({"id": k, "method": "textDocument/" + meth, "params": {"textDocument": td, "position": {
                "line": ln, "character": col}, "context": {"includeDeclaration": True}}})
            k += 1
    for meth in ("documentSymbol", "formatting"):
        reqs.append({"id": k, "method": "textDocument/" + meth, "params": {"textDocument": td, "options": {}}})
        k += 1
    if positions:
        ln, col = positions[len(positions) // 2]
        reqs.append({"id": k, "method": "textDocument/rename", "params": {"textDocument": td, "position": {
            "line": ln, "character": col}, "newName": "zz_renamed"}})
        k += 1
    reqs.append({"method": "textDocument/didChange", "params": {"textDocument": td, "contentChanges": [
        {"text": text + "\nfn broken( {\n"}]}})
    reqs += [{"id": k, "method": "shutdown"}, {"method": "exit"}]
    return b"".join(lsp_frame(r) for r in reqs)


def mcp_session():
    """MCP messages (one per line) that use every tool on files of the repository, plus protocol edge cases."""
    def call(i, tool, **args):
        return {"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": tool, "arguments": args}}
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": "p", "method": "ping"}]
    i = 10
    for f in ("examples/bank.klar", "examples/mistakes.klar", "examples/shapes.klar", "tests/native/traits.klar"):
        for name in ("klar_check", "klar_dev", "klar_outline", "klar_test"):
            msgs.append(call(i, name, file=f))
            i += 1
    msgs += [call(50, "klar_test", file="examples/bank.klar", filter="withdraw"),
             call(51, "klar_dev", file="examples/hello.klar", run=False),
             call(52, "klar_eval", expression="[1, 2].map(fn(x) => x * 3)"),
             call(53, "klar_eval", statements=["let a = 2"], expression="a * 21"),
             call(54, "klar_eval", expression="area(Shape.Circle(radius: 1.0))", file="examples/shapes.klar"),
             call(55, "klar_doc", query="split"), call(56, "klar_doc", query="List.sort"),
             call(57, "klar_refs", file="examples/bank.klar", name="deposit"),
             call(58, "klar_explain", code="E0201"), call(59, "klar_explain", code="X9999"), call(60, "klar_spec"),
             call(61, "klar_patch", file="examples/bank.klar", patch='{"edits": [{"find": "Alice", "in": "main"}]}',
                  dry_run=True),
             call(62, "klar_fix", file="examples/mistakes.klar", dry_run=True),
             call(63, "klar_check"), call(64, "klar_check", file=""), call(65, "nope"),
             {"jsonrpc": "2.0", "id": 66, "method": "resources/list"},
             {"jsonrpc": "2.0", "id": None, "method": "ping"}, [1, 2]]
    lines = [json.dumps(m) for m in msgs] + ["not json", "", "   "]
    return ("\n".join(lines) + "\n").encode()


def check_mcp(klarc):
    """`klarc mcp` == `klar mcp`: the same answer to every message of a session that uses every tool."""
    data = mcp_session()
    want = subprocess.run([sys.executable, "-m", "klar", "mcp"], input=data, capture_output=True, cwd=ROOT)
    got = subprocess.run([klarc, "mcp", "--klarc", klarc, "--lib", os.path.join(ROOT, "klar")], input=data,
                         capture_output=True, cwd=ROOT)
    a, b = want.stdout.decode().splitlines(), got.stdout.decode().splitlines()
    bad = sum(1 for x, y in zip(a, b) if x != y) + abs(len(a) - len(b))
    if bad:
        k = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
        print(f"DIFF mcp: message {k} of {len(a)}/{len(b)}\n  python: {a[k][:300] if k < len(a) else None}\n"
              f"  klar:   {b[k][:300] if k < len(b) else None}")
    print(f"mcp: {len(a) - bad}/{len(a)} messages identical")
    return bad


def check_lsp(klarc):
    """`klarc lsp` == `klar lsp`: the same messages for sessions on the examples, native tests and a few compiler
    files (and the code actions of the diagnostics of examples/mistakes.klar)."""
    import glob
    files = sorted(glob.glob(os.path.join(ROOT, "examples", "*.klar")) +
                   glob.glob(os.path.join(ROOT, "tests", "native", "*.klar"))) + [
        os.path.join(ROOT, "compiler", "fmt.klar"), os.path.join(ROOT, "klar", "std", "json.klar")]
    bad = total = 0
    lib = os.path.join(ROOT, "klar")
    for path in files:
        data = lsp_session(path, 40)
        if path.endswith("mistakes.klar"):
            first = subprocess.run([sys.executable, "-m", "klar", "lsp"], input=data, capture_output=True, cwd=ROOT)
            diags = [m for m in lsp_messages(first.stdout) if m.get("method") == "textDocument/publishDiagnostics"]
            uri = "file://" + os.path.abspath(path).replace(os.sep, "/")
            data = data.replace(lsp_frame({"method": "exit"}), b"") + lsp_frame(
                {"id": 99999, "method": "textDocument/codeAction", "params": {"textDocument": {"uri": uri},
                 "context": {"diagnostics": diags[0]["params"]["diagnostics"]}}}) + lsp_frame({"method": "exit"})
        want = subprocess.run([sys.executable, "-m", "klar", "lsp"], input=data, capture_output=True, cwd=ROOT)
        got = subprocess.run([klarc, "lsp", "--lib", lib], input=data, capture_output=True, cwd=ROOT)
        a, b = lsp_messages(want.stdout), lsp_messages(got.stdout)
        total += len(a)
        if (a, want.returncode) != (b, got.returncode):
            k = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
            bad += sum(1 for x, y in zip(a, b) if x != y) + abs(len(a) - len(b))
            print(f"DIFF lsp {short(path)}: message {k} of {len(a)}/{len(b)}\n"
                  f"  python: {str(a[k] if k < len(a) else None)[:300]}\n  klar:   {str(b[k] if k < len(b) else None)[:300]}")
    print(f"lsp: {total - bad}/{total} messages identical")
    return bad


REPL_SESSION = 'let xs = [3, 1, 2]\nxs.sort()\nfn double(n: Int) -> Int {\n  return n * 2\n}\nxs.map(double)\n"hello".upper()\nlet n = 5\nn + 1\nprint("side effect")\nn * 1.5\nlet n = 3\nnope(2)\n:type xs.len()\n:t "a" + "b"\ntype P { x: Int, y: Int }\nlet p = P { x: 1, y: 2 }\np\np.x + p.y\n[1, 2].get_or(5, 0) / ([1].len() - 1)\nlet d = 0\nvar z = 10\nz = z + n\nz\nassert z == 99\nSome("x")\nMap {}.set("k", [1.5])\n:defs\n:doc split\n:help\n:foo\nenum Color {\n  Red,\n  Green,\n}\nColor.Red\nlet total = xs.fold(0, fn(acc, v) => acc + v)\ntotal\n:reset\nxs\n1 +\n  2\n:quit\n'


def check_repl(klarc, d):
    """`klarc repl --plain` == `klar repl` on a scripted session (expressions, statements, declarations, errors,
    a runtime error, commands)."""
    from contextlib import redirect_stdout
    from klar.tools.repl import Repl
    out = io.StringIO()
    with redirect_stdout(out):
        Repl(cwd=d, out=out, inp=io.StringIO(REPL_SESSION)).loop()
    proc = subprocess.run([klarc, "repl", "--plain", "--lib", os.path.join(ROOT, "klar")], input=REPL_SESSION,
                          capture_output=True, text=True, encoding="utf-8", cwd=d)
    same = proc.stdout == out.getvalue()
    if not same:
        wl, hl = out.getvalue().split("\n"), proc.stdout.split("\n")
        i = next((i for i, (x, y) in enumerate(zip(wl, hl)) if x != y), min(len(wl), len(hl)))
        print(f"DIFF repl line {i + 1}: python {wl[i] if i < len(wl) else None!r}, klar {hl[i] if i < len(hl) else None!r}")
    print(f"repl: {'identical' if same else 'DIFFERENT'}")
    return 0 if same else 1


def check_coverage(klarc):
    """`klarc coverage` == `klar coverage` (text, --json, --main) on the examples and native test programs."""
    import glob
    files = sorted(glob.glob(os.path.join(ROOT, "examples", "*.klar")) +
                   glob.glob(os.path.join(ROOT, "tests", "native", "*.klar")))
    bad = runs = 0
    for path in files:
        for flags in ([], ["--json", "--main"]):
            runs += 1
            job = ["coverage", path] + flags
            want = cli_output(job)
            proc = subprocess.run([klarc] + job + ["--lib", os.path.join(ROOT, "klar")], capture_output=True, text=True,
                                  encoding="utf-8", stdin=subprocess.DEVNULL)
            if (proc.stdout, proc.returncode) != (want[0], want[2]):
                bad += 1
                print(f"DIFF coverage {short(path)} {flags}:\n  python: {want[0][:300]!r}\n  klar:   {proc.stdout[:300]!r}")
    print(f"coverage: {runs - bad}/{runs} reports identical")
    return bad


def check_profile(klarc):
    """`klarc profile --json` and `klar profile --json` count the same calls of the user functions and the same
    executions of each line (times differ: native code; built-ins are listed only by klar)."""
    bad = runs = 0
    for path in lowering_files():
        # (not the compiler, not the scripts that write files or run other programs: bench/, tools/, the fuzzer, and
        # not the programs that never end: `profile` has no time limit)
        if any(os.sep + d + os.sep in path for d in ("compiler", "bench", "tools", "limits")) or path.endswith("fuzz.klar"):
            continue
        runs += 1
        want = cli_output(["profile", path, "--json", "--top", "1000"])
        proc = subprocess.run([klarc, "profile", path, "--json", "--top", "1000", "--lib", os.path.join(ROOT, "klar")],
                              capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL)
        try:
            a, b = json.loads(want[0]), json.loads(proc.stdout)
        except ValueError:
            bad += 1
            print(f"DIFF profile {short(path)}: {want[0][:200]!r} / {proc.stdout[:200]!r} {proc.stderr[:200]!r}")
            continue
        if "stage" in a or "stage" in b:
            if a != b:
                bad += 1
                print(f"DIFF profile {short(path)}: {want[0][:300]!r} / {proc.stdout[:300]!r}")
            continue
        calls = [{f["function"]: f["calls"] for f in x["functions"] if not f["function"].startswith("<builtin>")}
                 for x in (a, b)]
        lines = [[(h["file"], h["line"], h["executions"]) for h in x["hot_lines"]] for x in (a, b)]
        if calls[0] != calls[1] or sorted(lines[0]) != sorted(lines[1]) or a["ok"] != b["ok"]:
            bad += 1
            print(f"DIFF profile {short(path)}: calls {calls[0] == calls[1]}, lines {sorted(lines[0]) == sorted(lines[1])}")
    print(f"profile: {runs - bad}/{runs} programs with the same counts")
    return bad


def check_tools_a(klarc, d):
    return check_new(klarc, d) + check_fmt_cli(klarc, d) + check_dev(klarc) + check_profile(klarc) + \
        check_coverage(klarc)


def check_tools_b(klarc, d):
    return check_repl(klarc, d) + check_lsp(klarc) + check_mcp(klarc) + check_view(klarc, d)


def check_tools_c(klarc, d):
    return check_eval(klarc, d) + check_sandbox(klarc, d) + check_limit(klarc, d) + check_spec_full(klarc) + \
        check_pkg(klarc, d) + \
        check_patch(klarc, [p for p in klar_files() if os.sep + "rt" + os.sep not in p
                            and os.sep + "compiler" + os.sep not in p][:80])


def check_tools_d(klarc, cases, part=0, parts=1):
    files = [p for p in cases + list(klar_files()) if not p.startswith(os.path.join(ROOT, "klar", "rt"))]
    return check_inspect(klarc, files[part::parts], f" ({part + 1}/{parts})" if parts > 1 else "")


def check_fix(klarc, cases):
    """`klarc fix` (compiler/commands.klar) == `klar fix` on every checker case: the same output and exit code and the
    same files afterwards, with the default fixes, with `--all --warnings`, and with `--json`."""
    import shutil
    from contextlib import redirect_stdout
    from klar.cli import main as cli_main
    bad = runs = 0
    with tempfile.TemporaryDirectory() as d:
        for k, main in enumerate(cases):
            for m, flags in enumerate(([], ["--all", "--warnings"], ["--json"])):
                runs += 1
                src = os.path.dirname(main)
                py_dir, k_dir = os.path.join(d, f"py{k}_{m}"), os.path.join(d, f"k{k}_{m}")
                shutil.copytree(src, py_dir)
                shutil.copytree(src, k_dir)
                out = io.StringIO()
                with redirect_stdout(out):
                    py_code = cli_main(["fix", os.path.join(py_dir, "main.klar")] + flags)
                proc = subprocess.run([klarc, "fix", os.path.join(k_dir, "main.klar"), "--lib", os.path.join(ROOT, "klar")]
                                      + flags, capture_output=True, text=True, encoding="utf-8")
                if (proc.stdout, proc.returncode) != (out.getvalue(), py_code):
                    bad += 1
                    wl, hl = out.getvalue().split("\n"), proc.stdout.split("\n")
                    i = next((i for i, (x, y) in enumerate(zip(wl, hl)) if x != y), min(len(wl), len(hl)))
                    print(f"DIFF fix {flags} case {k}: exit {py_code}/{proc.returncode}, line {i + 1}\n"
                          f"  python: {wl[i] if i < len(wl) else None!r}\n  klar:   {hl[i] if i < len(hl) else None!r}"
                          f"{proc.stderr[:300]}")
                elif tree(py_dir) != tree(k_dir):
                    bad += 1
                    print(f"DIFF fix {flags} case {k}: the files differ afterwards")
    print(f"fix: {runs - bad}/{runs} runs identical")
    return bad


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    interp = "--interp" in argv
    only = [a for a in argv if not a.startswith("--")]
    from klar.native.build import host_target
    if host_target() != "linux" and not interp and "--update" not in argv:
        # the Klar compiler is built and run as a Linux x86-64 executable; elsewhere only `--interp` works (slowly)
        print(f"selfhost: skipped on {host_target() or sys.platform} (needs Linux x86-64, or --interp)")
        return 0
    jobs = os.cpu_count() or 1
    if "-j" in argv:
        k = argv.index("-j")
        jobs = int(argv[k + 1])
        only = [a for i, a in enumerate(argv) if not a.startswith("-") and i != k + 1]
    if "--update" in argv and not only:
        return check_builtin_sigs(True)
    stages = {"lexer", "parser", "lowering", "emit", "fmt", "checker", "report", "fix"}
    if set(only) - stages:
        print(f"selfhost: unknown stage(s) {', '.join(sorted(set(only) - stages))} (stages: {', '.join(sorted(stages))})")
        return 2
    files = list(klar_files())
    started = time.time()
    with tempfile.TemporaryDirectory() as d:
        lex_files = files + write_snippets(d, "lex", ERROR_SNIPPETS)
        parse_files = files + write_snippets(d, "parse", PARSE_SNIPPETS) + lex_files[len(files):]
        bad = check_builtin_sigs("--update" in argv)
        tasks = []
        if not only or "lexer" in only:
            tasks.append(("lexer", check_lexer, (lex_files, interp)))
        if not only or "parser" in only:
            tasks.append(("parser", check_parser, (parse_files, interp)))
        if not only or "emit" in only:
            for k in range(3):
                tasks.append((f"emit {k + 1}/3", check_emit, (interp, k, 3)))
        if not only or "lowering" in only:
            tasks.append(("lowering", check_lowering, (interp,)))
            tasks.append(("lowering of tests", check_lowering, (interp, True)))
        if not only or "fmt" in only:
            tasks.append(("fmt", check_fmt, (files + messy_variants(files, d), interp)))
        if not only or "checker" in only or "report" in only:
            cases = files + write_cases(d)
            if not only or "checker" in only:
                tasks.append(("checker", check_checker, (cases, interp)))
            if not only or "report" in only:
                tasks.append(("report", check_report, (cases, interp)))
        later = []
        if not only or "fix" in only:
            # the command-line tools of klarc, against the Python ones: they need klarc itself, built below
            fixcases = write_cases(os.path.join(d, "fixcases"))
            klarc = os.path.join(d, "klarc")
            for name, fn in (("new, fmt, dev, profile, coverage", check_tools_a),
                             ("repl, lsp, mcp, view", check_tools_b),
                             ("eval, sandbox, limit, packages, patch", check_tools_c)):
                sub = os.path.join(d, "tools-" + fn.__name__[-1])
                os.makedirs(sub)
                later.append((name, fn, (klarc, sub)))
            for k in range(4):
                later.append((f"inspect {k + 1}/4", check_tools_d, (klarc, fixcases, k, 4)))
            later.append(("fix", check_fix, (klarc, fixcases)))
        bad += run_tasks(tasks, later, jobs, klarc if later else None)
    print(f"selfhost: {'ok' if not bad else f'{bad} difference(s)'} in {time.time() - started:.0f} s ({jobs} jobs)")
    return 1 if bad else 0


def run_task(name, fn, args):
    """One stage in a worker process: (problems, what it printed, seconds)."""
    from contextlib import redirect_stdout
    out = io.StringIO()
    t = time.time()
    with redirect_stdout(out):
        n = fn(*args)
    return n, out.getvalue(), time.time() - t


def run_tasks(tasks, later, jobs, klarc):
    """Runs the stages, `jobs` at a time; `later` ones once klarc is built (it is built meanwhile, by the Python
    backend). Each stage's output is printed when it ends, with its time."""
    def report(name, res):
        n, text, secs = res
        sys.stdout.write(text.rstrip("\n") + f"   [{name}: {secs:.0f} s]\n")
        sys.stdout.flush()
        return n
    if jobs <= 1:
        bad = sum(report(name, run_task(name, fn, args)) for name, fn, args in tasks)
        if later:
            from klar.native.build import build
            build(os.path.join(ROOT, "compiler", "klarc.klar"), out=klarc, target="linux")
            bad += sum(report(name, run_task(name, fn, args)) for name, fn, args in later)
        return bad
    import concurrent.futures as cf
    import multiprocessing
    bad = 0
    ctx = multiprocessing.get_context("fork")
    with cf.ProcessPoolExecutor(max_workers=jobs, mp_context=ctx) as pool:
        futs = {pool.submit(run_task, name, fn, args): name for name, fn, args in tasks}
        if later:
            from klar.native.build import build
            build(os.path.join(ROOT, "compiler", "klarc.klar"), out=klarc, target="linux")
            futs.update({pool.submit(run_task, name, fn, args): name for name, fn, args in later})
        for f in cf.as_completed(futs):
            bad += report(futs[f], f.result())
    return bad


if __name__ == "__main__":
    sys.exit(main())
