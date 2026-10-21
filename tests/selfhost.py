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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from klar.diagnostics import KlarSyntaxError  # noqa: E402
from klar.lexer import tokenize  # noqa: E402
from klar.nodes import to_json  # noqa: E402
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
        return [{"error": d.code, "message": d.message, "span": [d.span.line, d.span.col]}]
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
        return {"error": d.code, "message": d.message, "span": [d.span.line, d.span.col]}
    tree = json.loads(json.dumps(to_json(prog), default=lambda sp: [sp.line, sp.col, sp.end_line, sp.end_col]))
    del tree["file"]
    return strip_ids(tree)


def strip_ids(x):
    if isinstance(x, dict):
        return {k: strip_ids(v) for k, v in x.items() if not (k == "id" and "node" in x)}
    if isinstance(x, list):
        return [strip_ids(v) for v in x]
    return x


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
    return os.path.relpath(path, ROOT) if path.startswith(ROOT) else os.path.basename(path)


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


def main():
    interp = "--interp" in sys.argv
    only = [a for a in sys.argv[1:] if not a.startswith("--")]
    files = list(klar_files())
    with tempfile.TemporaryDirectory() as d:
        lex_files = files + write_snippets(d, "lex", ERROR_SNIPPETS)
        parse_files = files + write_snippets(d, "parse", PARSE_SNIPPETS) + lex_files[len(files):]
        bad = 0
        if not only or "lexer" in only:
            bad += check_lexer(lex_files, interp)
        if not only or "parser" in only:
            bad += check_parser(parse_files, interp)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
