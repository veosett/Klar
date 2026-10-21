#!/usr/bin/env python3
"""AI-ergonomics benchmark: how early does each language catch the mistakes AI models typically make?

    python bench/ai/run_ai_bench.py              # all cases, all languages found on this machine
    python bench/ai/run_ai_bench.py -l klar rust # selected languages
    python bench/ai/run_ai_bench.py --name my-pc

Every case in bench/ai/cases/<id>/ is the SAME small program with the SAME typical mistake, written
idiomatically in Klar, Python (plain and with mypy), TypeScript (tsc --strict), Java, Go (+ go vet),
Rust and C++ (-Wall -Wextra). The line with the mistake is marked `BUG`. For each program we use the
language's normal developer loop (type-check / compile with warnings, then run) and record:

  compile   the compiler / type checker rejected the program        (best: the AI fixes it before running)
  design    the mistake cannot happen in this language (correct output)
  warning   it compiled, but a warning pointed at the mistake
  runtime   it compiled and crashed with an error at run time      (found only if that path is executed)
  silent    it ran and printed a WRONG result with no error         (worst: the AI believes it works)

plus whether the message points at the right line, whether it suggests a fix, and its size in tokens.
No language model is called: the benchmark is deterministic and reproducible.
"""
import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CASES = os.path.join(HERE, "cases")
EXE = ".exe" if os.name == "nt" else ""
HINT = re.compile(r"(?i)\bhelp:|did you mean|\bhint\b|\"fix\"|consider |perhaps|suggestion|maybe you meant")


def tool(*names):
    for n in names:
        p = shutil.which(n)
        if p:
            return p
        for extra in ("~/.cargo/bin", "~/go/bin", "/usr/local/go/bin"):
            q = os.path.expanduser(os.path.join(extra, n + EXE))
            if os.path.exists(q):
                return q
    return None


def run(cmd, cwd, timeout=60):
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                           env=dict(os.environ, PYTHONPATH=ROOT, NO_COLOR="1", TERM="dumb"))
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return -999, "", "timeout"


def languages():
    py = sys.executable
    L = {}
    L["klar"] = dict(file="prog.klar", label="Klar",
                     check=lambda d: [py, "-m", "klar", "check", "prog.klar"],
                     build=lambda d: [py, "-m", "klar", "build", "-q", "prog.klar", "-o", os.path.join(d, "prog" + EXE)],
                     run=lambda d: [os.path.join(d, "prog" + EXE)])
    L["python"] = dict(file="prog.py", label="Python", run=lambda d: [py, "prog.py"])
    mypy = tool("mypy")
    if mypy:
        L["python+mypy"] = dict(file="prog.py", label="Python + mypy",
                                check=lambda d: [mypy, "--no-error-summary", "--hide-error-context",
                                                 "--cache-dir", os.path.join(d, "mypy"), "prog.py"],
                                run=lambda d: [py, "prog.py"])
    tsc, node = tool("tsc"), tool("node")
    if tsc and node:
        L["typescript"] = dict(file="prog.ts", label="TypeScript (strict)",
                               check=lambda d: [tsc, "--strict", "--target", "es2022", "--module", "commonjs",
                                                "--outDir", d, "prog.ts"],
                               run=lambda d: [node, os.path.join(d, "prog.js")], check_blocks=False)
    javac, java = tool("javac"), tool("java")
    if javac and java:
        L["java"] = dict(file="Main.java", label="Java",
                         build=lambda d: [javac, "-Xlint:all", "-d", d, "Main.java"],
                         run=lambda d: [java, "-cp", d, "Main"])
    go = tool("go")
    if go:
        L["go"] = dict(file="prog.go", label="Go (+ vet)",
                       check=lambda d: [go, "vet", "prog.go"], check_is_warning=True,
                       build=lambda d: [go, "build", "-o", os.path.join(d, "prog" + EXE), "prog.go"],
                       run=lambda d: [os.path.join(d, "prog" + EXE)])
    rustc = tool("rustc")
    if rustc:
        L["rust"] = dict(file="prog.rs", label="Rust",
                         build=lambda d: [rustc, "--edition", "2021", "-o", os.path.join(d, "prog" + EXE), "prog.rs"],
                         run=lambda d: [os.path.join(d, "prog" + EXE)])
    gxx = tool("g++", "clang++")
    if gxx:
        L["cpp"] = dict(file="prog.cpp", label="C++ (-Wall -Wextra)",
                        build=lambda d: [gxx, "-std=c++17", "-Wall", "-Wextra", "-O0", "-o",
                                         os.path.join(d, "prog" + EXE), "prog.cpp"],
                        run=lambda d: [os.path.join(d, "prog" + EXE)])
    return L


def bug_line(path):
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            if "BUG" in line:
                return i
    return None


def mentions_line(text, fname, line):
    if line is None:
        return False
    stem = re.escape(fname)
    pats = [rf"{stem}:{line}\b", rf"{stem}\({line},", rf'{stem}", line {line}\b', rf"{stem}:{line}:",
            rf'"line": {line}\b', rf"at .*\({stem}:{line}\)"]
    return any(re.search(p, text) for p in pats)


def warning_lines(text, fname):
    """Line numbers that compiler warnings point at (gcc/clang, rustc, javac, go vet)."""
    lines = set()
    stem = re.escape(fname)
    for m in re.finditer(rf"{stem}:(\d+)(?::\d+)?: warning", text):
        lines.add(int(m.group(1)))
    # rustc / Klar style: "warning...\n  --> file:LINE" followed by a source snippet "LINE | code"
    for block in re.split(r"\n(?=(?:warning|error)\b)", text):
        if block.startswith("warning") and f"--> {fname}:" in block:
            lines.update(int(n) for n in re.findall(r"^\s*(\d+)\s*\|", block, re.M))
            lines.update(int(n) for n in re.findall(rf"--> {stem}:(\d+)", block))
    return lines


def evaluate(lang, cfg, case_dir, expected, work):
    src = os.path.join(case_dir, cfg["file"])
    d = tempfile.mkdtemp(dir=work)
    shutil.copy(src, os.path.join(d, cfg["file"]))
    line = bug_line(src)
    diag = ""
    if "check" in cfg:
        code, out, err = run(cfg["check"](d), d)
        text = out + err
        if lang == "klar":
            if code != 0:
                return result("compile", text, cfg["file"], line)
            if line in warning_lines(text, cfg["file"]):
                diag = text
        elif code != 0:
            if cfg.get("check_is_warning"):
                diag = text
            elif cfg.get("check_blocks", True):
                return result("compile", text, cfg["file"], line)
            else:
                return result("compile", text, cfg["file"], line)
    if "build" in cfg:
        code, out, err = run(cfg["build"](d), d, timeout=180)
        text = out + err
        if code != 0:
            return result("compile", text, cfg["file"], line)
        if line in warning_lines(text, cfg["file"]):
            diag = diag or text
    code, out, err = run(cfg["run"](d), d, timeout=20)
    got = out.strip()
    if diag:
        r = result("warning", diag, cfg["file"], line)
    elif code != 0:
        r = result("runtime", err or out or f"exit code {code}", cfg["file"], line)
    elif got == expected:
        r = result("design", "", cfg["file"], line)
    else:
        r = result("silent", "", cfg["file"], line)
    r["output"] = got[:120]
    return r


def result(outcome, text, fname, line):
    return {"outcome": outcome, "points_to_line": mentions_line(text, fname, line) if text else False,
            "hint": bool(HINT.search(text)) if text else False, "tokens": round(len(text) / 4)}


ICON = {"compile": "✅ compile", "design": "🛡️ by design", "warning": "⚠️ warning", "runtime": "💥 runtime",
        "silent": "❌ silent", None: "—"}
WEIGHT = {"compile": 1.0, "design": 1.0, "warning": 0.5, "runtime": 0.25, "silent": 0.0}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-l", "--lang", nargs="*")
    ap.add_argument("-c", "--case", nargs="*")
    ap.add_argument("--name", default=(platform.node() or "host").split(".")[0])
    ap.add_argument("--out", default=os.path.join(HERE, "results"))
    args = ap.parse_args()
    langs = languages()
    if args.lang:
        langs = {k: v for k, v in langs.items() if k in args.lang}
    cases = sorted(c for c in os.listdir(CASES) if os.path.isdir(os.path.join(CASES, c)))
    if args.case:
        cases = [c for c in cases if any(c.startswith(x) for x in args.case)]
    results = {}
    with tempfile.TemporaryDirectory() as work:
        for c in cases:
            cdir = os.path.join(CASES, c)
            with open(os.path.join(cdir, "case.json"), encoding="utf-8") as f:
                meta = json.load(f)
            results[c] = {"meta": meta, "langs": {}}
            for lang, cfg in langs.items():
                if not os.path.exists(os.path.join(cdir, cfg["file"])):
                    continue
                r = evaluate(lang, cfg, cdir, meta["expected"], work)
                results[c]["langs"][lang] = r
                print(f"  {c:<24} {lang:<12} {r['outcome']:<8} line={'y' if r['points_to_line'] else 'n'} "
                      f"hint={'y' if r['hint'] else 'n'} tokens={r['tokens']}", flush=True)
    report = render(results, langs)
    print()
    print(report)
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, f"{args.name}.md"), "w", encoding="utf-8") as f:
        f.write(report + "\n")
    with open(os.path.join(args.out, f"{args.name}.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)


def render(results, langs):
    order = list(langs)
    lines = ["# AI-ergonomics benchmark: when is a typical AI mistake caught?", "",
             "| mistake | " + " | ".join(langs[l]["label"] for l in order) + " |",
             "|---|" + "---|" * len(order)]
    for c, rs in results.items():
        row = [rs["meta"]["title"] + f" — *{rs['meta']['mistake']}*"]
        for l in order:
            r = rs["langs"].get(l)
            row.append(ICON[r["outcome"]] if r else "n/a")
        lines.append("| " + " | ".join(row) + " |")
    stats = {}
    for l in order:
        rs = [x["langs"][l] for x in results.values() if l in x["langs"]]
        n = len(rs)
        cnt = {k: sum(1 for r in rs if r["outcome"] == k) for k in WEIGHT}
        reported = [r for r in rs if r["outcome"] in ("compile", "warning", "runtime")]
        stats[l] = {
            "n": n,
            "before_run": cnt["compile"] + cnt["design"],
            "silent": cnt["silent"],
            "runtime": cnt["runtime"],
            "warning": cnt["warning"],
            "score": round(100 * sum(WEIGHT[r["outcome"]] for r in rs) / n) if n else 0,
            "line": f"{sum(r['points_to_line'] for r in reported)}/{len(reported)}",
            "hint": f"{sum(r['hint'] for r in reported)}/{len(reported)}",
            "tokens": round(sum(r["tokens"] for r in reported) / len(reported)) if reported else 0,
        }
    lines += ["", "| summary | " + " | ".join(langs[l]["label"] for l in order) + " |", "|---|" + "---:|" * len(order)]
    rows = [("**safety score** (compile/design = 1, warning = ½, runtime = ¼, silent = 0)", lambda s: f"**{s['score']}**"),
            ("stopped before running (compile error or impossible by design)", lambda s: f"{s['before_run']}/{s['n']}"),
            ("only a warning", lambda s: f"{s['warning']}/{s['n']}"),
            ("crash at run time", lambda s: f"{s['runtime']}/{s['n']}"),
            ("**silently wrong result**", lambda s: f"**{s['silent']}/{s['n']}**"),
            ("message points at the mistaken line", lambda s: s["line"]),
            ("message suggests a fix", lambda s: s["hint"]),
            ("average message size, tokens", lambda s: str(s["tokens"]))]
    for title, f in rows:
        lines.append("| " + title + " | " + " | ".join(f(stats[l]) for l in order) + " |")
    lines += ["", "✅ rejected by the compiler / type checker · 🛡️ the mistake cannot happen (correct result) · "
                  "⚠️ compiled with a warning at the mistake · 💥 crashed at run time · ❌ wrong result, no error",
              "", f"Machine: {platform.system()} {platform.machine()}, Python {platform.python_version()}."]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
