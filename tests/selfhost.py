"""Self-hosting check: the parts of the compiler written in Klar (compiler/*.klar) must behave exactly like
the Python implementation, on every .klar file of the repository and on error snippets:

* stage 3a, the lexer (compiler/lexer.klar): same tokens (kinds, values, spans, string parts) and the same
  errors (code, message, position) as klar/lexer.py;
* stage 3b, the parser (compiler/parser.klar): the same syntax tree (klar/nodes.py `to_json`, every node with
  its span) and the same syntax errors as klar/parser.py.

    python tests/selfhost.py            # native builds of compiler/dump_*.klar (fast)
    python tests/selfhost.py --interp   # run the Klar lexer and parser in the reference interpreter
"""
import json
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
    out = ["// Generated by `python tests/selfhost.py --update` from klar/builtins.py and klar/native/intrinsics.py:",
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
           f"  return {pairs(FOREIGN_NOTES.items())}", "}", ""]
    return "\n".join(out)


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
    """Diagnostics of `klar check path` without the safety analysis (a separate pass, not ported yet)."""
    import klar.safety
    from klar.loader import load_path
    saved = klar.safety.analyze
    klar.safety.analyze = lambda checker, program: []
    try:
        loaded = load_path(path)
    finally:
        klar.safety.analyze = saved
    return sorted_diags({"severity": d.severity, "code": d.code, "message": d.message, "hint": d.hint,
                         "file": d.span.file, "span": [d.span.line, d.span.col]} for d in loaded.diags)


def sorted_diags(ds):
    return sorted(ds, key=lambda d: (d["file"], d["span"], d["code"], d["message"], d["severity"], d["hint"] or ""))


def klar_diags(paths, interp):
    out = run_driver("dump_check.klar", [os.path.join(ROOT, "klar")] + paths, interp)
    result, cur = {}, None
    for line in out.splitlines():
        obj = json.loads(line)
        if set(obj) == {"file"}:
            cur = obj["file"]
            result[cur] = []
        else:
            result[cur].append(obj)
    return {k: sorted_diags(v) for k, v in result.items()}


def check_checker(files, interp):
    got = klar_diags(files, interp)
    bad = total = 0
    for path in files:
        want = python_diags(path)
        have = got.get(path)
        total += len(want)
        if have != want:
            bad += 1
            first = next((k for k, (a, b) in enumerate(zip(want, have or [])) if a != b),
                         min(len(want), len(have or [])))
            print(f"DIFF {short(path)}: diagnostic {first} of {len(want)} (klar: {len(have or [])})\n"
                  f"  python: {want[first] if first < len(want) else None}\n"
                  f"  klar:   {have[first] if have and first < len(have) else None}")
    print(f"checker: {len(files) - bad}/{len(files)} files identical ({total} diagnostics)")
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
        if not only or "checker" in only:
            bad += check_checker(files + write_cases(d), interp)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
