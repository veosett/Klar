#!/usr/bin/env python3
"""Agent loop latency: seconds from a saved edit to a verdict ("types ok, tests pass" or "here is the error").

    python bench/ai/loop_latency.py --klarc ./klarc                   # the own suite (24 tasks)
    python bench/ai/loop_latency.py --klarc ./klarc --suite humaneval --limit 40

An agent edits a file and asks the tool chain for a verdict, many times per task. For every task of the suite, on
its reference solution, two edits are checked:
  correct     the reference solution: the verdict must be "pass";
  type error  the same file plus an unused helper that returns an Int as a Str: only a type checker sees it, so
              the verdict must be "fail" (plain `python` says "pass": a wrong verdict).
Tool chains: klarc (native, a standalone binary), `klar test` (the Python implementation), python, mypy + python
(cold, and with a warm mypy daemon as in an editor), tsc --strict + node. Each runs in a fresh directory, as the
benchmark harness does (llm_bench.py `evaluate`). Prints the median and the total per chain and edit, and how many
verdicts were right.
"""
import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import llm_bench as lb  # noqa: E402

BAD = {
    "klar": "\nfn zz_helper(n: Int) -> Str {\n  return n + 1\n}\n",
    "python": "\n\ndef zz_helper(n: int) -> str:\n    return n + 1\n",
    "typescript": "\nexport function zzHelper(n: number): string {\n  return n + 1;\n}\n",
}
TESTS = {"klar": lb.tests_klar, "python": lb.tests_python, "typescript": lb.tests_typescript}


def chains(klarc):
    tsc = shutil.which("tsc")
    out = {}
    if klarc:
        out["klarc test (native)"] = ("klar", [[klarc, "test", "-q", "check.klar"]])
    out["klar test (Python)"] = ("klar", [[sys.executable, "-m", "klar", "test", "-q", "check.klar"]])
    out["python"] = ("python", [[sys.executable, "check.py"]])
    if shutil.which("mypy"):
        out["mypy + python"] = ("python", [["mypy", "--no-incremental", "check.py", "solution.py"],
                                           [sys.executable, "check.py"]])
    if shutil.which("dmypy"):
        out["mypy daemon + python"] = ("python", [["dmypy", "run", "--", "check.py", "solution.py"],
                                                  [sys.executable, "check.py"]])
    if tsc:
        out["tsc + node"] = ("typescript", [[tsc, "--strict", "--target", "es2020", "--module", "commonjs", "--outDir",
                                             "out", "check.ts", "solution.ts"], ["node", os.path.join("out", "check.js")]])
    return out


def timed(cmd, d):
    env = dict(os.environ, PYTHONPATH=ROOT, NO_COLOR="1")
    t = time.perf_counter()
    p = subprocess.run(cmd, cwd=d, capture_output=True, text=True, env=env, timeout=300)
    return time.perf_counter() - t, p.returncode


def verdict(name, lang, steps, refs, task, bad):
    with open(os.path.join(refs, lang, f"{task['id']}.{lb.EXT[lang]}"), encoding="utf-8") as f:
        code = f.read() + (BAD[lang] if bad else "")
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, f"solution.{lb.EXT[lang]}"), "w", encoding="utf-8") as f:
            f.write(code)
        with open(os.path.join(d, f"check.{lb.EXT[lang]}"), "w", encoding="utf-8") as f:
            f.write(TESTS[lang](task))
        daemon = "daemon" in name
        if daemon:                       # warm: the daemon has seen the files once, as in an editor
            timed(steps[0], d)
        total, result = 0.0, "pass"
        for cmd in steps:
            dt, rc = timed(cmd, d)
            total += dt
            if rc != 0:
                result = "fail"
                break
        if daemon:
            timed(["dmypy", "stop"], d)
        return total, result


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--klarc", help="the native compiler (a standalone binary)")
    ap.add_argument("--suite", choices=sorted(lb.SUITES), default="own")
    ap.add_argument("--limit", type=int, default=0, help="only the first N tasks")
    ap.add_argument("--json", help="also write the results here")
    args = ap.parse_args()
    tasks_path, refs = lb.SUITES[args.suite]
    with open(tasks_path, encoding="utf-8") as f:
        tasks = json.load(f)
    if args.limit:
        tasks = tasks[:args.limit]
    rows = []
    for name, (lang, steps) in chains(os.path.abspath(args.klarc) if args.klarc else None).items():
        for bad in (False, True):
            times, right = [], 0
            for t in tasks:
                dt, v = verdict(name, lang, steps, refs, t, bad)
                times.append(dt)
                right += v == ("fail" if bad else "pass")
            edit = "type error" if bad else "correct"
            rows.append({"chain": name, "edit": edit, "median_ms": round(statistics.median(times) * 1000),
                         "total_s": round(sum(times), 2), "right": right, "tasks": len(tasks)})
            print(f"{name:22} {edit:10}  median {statistics.median(times) * 1000:6.0f} ms  total {sum(times):6.1f} s"
                  f"  right verdicts {right}/{len(tasks)}", flush=True)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=1)


if __name__ == "__main__":
    main()
