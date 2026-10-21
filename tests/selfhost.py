"""Self-hosting check: the parts of the compiler written in Klar (compiler/*.klar) must behave exactly like
the Python implementation. Stage 3a: the lexer — same tokens (kinds, values, spans, string parts) and the
same errors (code, message, position) on every .klar file of the repository and on error snippets.

    python tests/selfhost.py            # native build of compiler/dump_tokens.klar (fast)
    python tests/selfhost.py --interp   # run the Klar lexer in the reference interpreter
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

ERROR_SNIPPETS = [
    "let x = a && b\n", "x || y\n", "i++\n", "a += 1\n", "Color::Red\n", "if !x {}\n", "f(x);\n", "let s = 'a'\n",
    "x & y\n", "x | y\n", "x ^ y\n", "~x\n", "x << 2\n", "x >> 2\n", "# comment\n", "@decorator\n", "`code`\n",
    "\"unterminated\n", "\"bad \\q escape\"\n", "\"open {interp\n", "\"{\"nested\"}\"\n", "\"{ }\"\n", "12px\n",
    "1.5e3\n", "3_000x\n", "let é = 1 ∑\n", "\"\\", "a;b\n",
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


def klar_tokens(paths, interp):
    driver = os.path.join(ROOT, "compiler", "dump_tokens.klar")
    cmd = [sys.executable, "-m", "klar", "run"] + (["--interp"] if interp else []) + [driver] + paths
    out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", cwd=ROOT).stdout
    result, cur = {}, None
    for line in out.splitlines():
        obj = json.loads(line)
        if set(obj) == {"file"}:
            cur = obj["file"]
            result[cur] = []
        else:
            result[cur].append(obj)
    return result


def main():
    interp = "--interp" in sys.argv
    files = list(klar_files())
    with tempfile.TemporaryDirectory() as d:
        for i, snippet in enumerate(ERROR_SNIPPETS):
            p = os.path.join(d, f"snippet{i}.klar")
            with open(p, "w", encoding="utf-8") as f:
                f.write(snippet)
            files.append(p)
        got = klar_tokens(files, interp)
        bad = 0
        tokens = 0
        for path in files:
            with open(path, encoding="utf-8") as f:
                want = python_tokens(f.read())
            have = got.get(path)
            tokens += len(want)
            if have != want:
                bad += 1
                name = os.path.relpath(path, ROOT) if path.startswith(ROOT) else os.path.basename(path)
                first = next((k for k, (a, b) in enumerate(zip(want, have or [])) if a != b),
                             min(len(want), len(have or [])))
                print(f"DIFF {name}: token {first}\n  python: {want[first] if first < len(want) else None}\n"
                      f"  klar:   {(have or [None] * (first + 1))[first] if have and first < len(have) else None}")
    print(f"\nlexer: {len(files) - bad}/{len(files)} files identical ({tokens} tokens)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
