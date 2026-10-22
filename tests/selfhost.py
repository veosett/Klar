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
    python tests/selfhost.py --update          # regenerate compiler/builtin_sigs.klar
"""
import json
import struct
import os
import subprocess
import sys
import tempfile
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
    "1.5e3\n", "3_000x\n", "let é = 1 ∑\n", "\"\\", "a;b\n",
]

PARSE_SNIPPETS = [
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
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("{", "\\{").replace("}", "\\}") + '"'


def builtin_sigs_source():
    """compiler/builtin_sigs.klar: the built-in signatures of klar/builtins.py and klar/native/intrinsics.py, as
    Klar data (the Klar checker parses them with the Klar parser, like the Python checker does)."""
    from klar.builtins import FOREIGN_METHODS, FOREIGN_NOTES, GLOBALS, METHODS
    from klar.native.intrinsics import SYS_SIGNATURES

    def str_list(items, indent="    "):
        return "[\n" + "".join(f"{indent}{klar_string(x)},\n" for x in items) + "  ]"

    def pairs(items):
        return "[\n" + "".join(f"    Pair {{ first: {klar_string(a)}, second: {klar_string(b)} }},\n"
                               for a, b in items) + "  ]"
    out = ["// Generated by `python tests/selfhost.py --update` from klar/builtins.py, klar/native/intrinsics.py and",
           "// the list of klar/rt/*.klar:",
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
           "/// The files of the runtime (klar/rt), which form one module.",
           "pub fn rt_files() -> List[Str] {", f"  return {str_list(rt_files())}", "}", ""]
    return "\n".join(out)


def rt_files():
    return sorted(f for f in os.listdir(os.path.join(ROOT, "klar", "rt")) if f.endswith(".klar"))


BUILTIN_SIGS = os.path.join(ROOT, "compiler", "builtin_sigs.klar")


def check_builtin_sigs(update):
    want = builtin_sigs_source()
    try:
        with open(BUILTIN_SIGS, encoding="utf-8") as f:
            have = f.read()
    except OSError:
        have = None
    if have == want:
        return 0
    if update:
        with open(BUILTIN_SIGS, "w", encoding="utf-8", newline="\n") as f:
            f.write(want)
        print("updated compiler/builtin_sigs.klar")
        return 0
    print("DIFF compiler/builtin_sigs.klar is out of date: run `python tests/selfhost.py --update`")
    return 1


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
        blocks = [d for d in loaded.main.program.decls if isinstance(d, N.TestDecl)]
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


TARGETS = (("linux", "elf"), ("windows", "exe"), ("linux-arm64", "a64"))


def check_emit(interp):
    """Executables built by the Klar backend (compiler/dump_exe.klar) == executables built by `klar build`."""
    from klar.native.build import build
    from klar.native.lower import NativeUnsupported
    files = lowering_files()
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
        out = run_driver("dump_exe.klar", [os.path.join(ROOT, "klar"), d] + files, interp)
        got = dict(line.split("\t") for line in out.splitlines())
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
    print(f"emit: {n - bad}/{n} executables identical ({n_bytes} bytes)")
    return bad


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    interp = "--interp" in argv
    only = [a for a in argv if not a.startswith("--")]
    files = list(klar_files())
    with tempfile.TemporaryDirectory() as d:
        lex_files = files + write_snippets(d, "lex", ERROR_SNIPPETS)
        parse_files = files + write_snippets(d, "parse", PARSE_SNIPPETS) + lex_files[len(files):]
        bad = check_builtin_sigs("--update" in argv)
        if not only or "lexer" in only:
            bad += check_lexer(lex_files, interp)
        if not only or "parser" in only:
            bad += check_parser(parse_files, interp)
        if not only or "lowering" in only:
            bad += check_lowering(interp)
            bad += check_lowering(interp, tests=True)
        if not only or "emit" in only:
            bad += check_emit(interp)
        if not only or "checker" in only:
            bad += check_checker(files + write_cases(d), interp)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
