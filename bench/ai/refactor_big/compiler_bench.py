#!/usr/bin/env python3
"""A change in the real compiler: the same request on the Klar implementation written in Klar and in Python.

    python bench/ai/refactor_big/compiler_bench.py prompt --lang klar --dir WORK
    python bench/ai/refactor_big/compiler_bench.py submit --lang klar --dir WORK --run RUN
    python bench/ai/refactor_big/compiler_bench.py validate --lang klar --dir WORK      # all the checks, shown in full
    python bench/ai/refactor_big/compiler_bench.py report --run RUN

`prompt` copies the implementation into WORK (`compiler/` or `klar/`) and prints the request of b2_compiler/task.md.
`submit` builds it if it needs building, runs the visible checks of b2_compiler/checks.py and answers with their failures;
the held-out checks run too, are recorded and never shown. At most --attempts attempts.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(HERE, "b2_compiler"))
from checks import CHECKS  # noqa: E402

EXE = "klarc.exe" if os.name == "nt" else "klarc"
TIMEOUT = 120


def shell(cmd, cwd, env=None, timeout=TIMEOUT):
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                           env=dict(os.environ, NO_COLOR="1", **(env or {})))
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"timeout after {timeout} s"


def build(lang, work):
    """The command that runs this implementation, or the reason it cannot be built."""
    work = os.path.abspath(work)
    if lang == "python":
        code, _, err = shell([sys.executable, "-c", "import klar.cli"], work, {"PYTHONPATH": work})
        return ([sys.executable, "-m", "klar"], {"PYTHONPATH": work}, "") if code == 0 else (None, None, err[-4000:])
    out = os.path.join(tempfile.mkdtemp(), EXE)
    code, stdout, err = shell([sys.executable, "-m", "klar", "build", "compiler/klarc.klar", "-o", out], work, {"PYTHONPATH": ROOT}, timeout=600)
    return ([out], {}, "") if code == 0 else (None, None, (stdout + err)[-4000:])


def run_check(check, tool, env):
    """The list of what went wrong, empty when the check passes."""
    with tempfile.TemporaryDirectory() as d:
        if "src" in check:
            with open(os.path.join(d, "p.klar"), "w", encoding="utf-8", newline="\n") as f:
                f.write(check["src"])
        code, out, err = shell(tool + check["cmd"], d, env)
        both = out + err
        wrong = []
        if "code" in check and code != check["code"]:
            wrong.append(f"exit code {code}, expected {check['code']}")
        if "out" in check and out.replace("\r\n", "\n") != check["out"]:
            wrong.append(f"printed {out!r}, expected {check['out']!r}")
        wrong += [f"the output lacks {s!r}" for s in check.get("has", []) if s not in both]
        wrong += [f"the output has {s!r}" for s in check.get("lacks", []) if s in both]
        if "after" in check or "after_has" in check:
            with open(os.path.join(d, "p.klar"), encoding="utf-8") as f:
                text = f.read().replace("\r\n", "\n")
            if "after" in check and text != check["after"]:
                wrong.append(f"the file became {text!r}, expected {check['after']!r}")
            wrong += [f"the file lacks {s!r}" for s in check.get("after_has", []) if s not in text]
            wrong += [f"the file still has {s!r}" for s in check.get("after_lacks", []) if s in text]
        if wrong:
            wrong.append("output: " + both[-500:])
        return wrong


def evaluate(lang, work):
    tool, env, why = build(lang, work)
    if tool is None:
        return {"stage": "build", "feedback": why, "failed": [c["name"] for c in CHECKS], "details": {}}
    details = {c["name"]: run_check(c, tool, env) for c in CHECKS}
    return {"stage": "checks", "failed": [n for n, w in details.items() if w], "details": details, "feedback": ""}


def cmd_prompt(a):
    os.makedirs(a.dir, exist_ok=True)
    if a.lang == "klar":
        shutil.copytree(os.path.join(ROOT, "compiler"), os.path.join(a.dir, "compiler"), dirs_exist_ok=True)
        what = ("This is the compiler of Klar written in Klar itself, in `compiler/` (entry: `compiler/klarc.klar`). Build it with "
                f"`python -m klar build compiler/klarc.klar -o {EXE}` and run the result as the `klar` command: `./{EXE} check x.klar`.")
    else:
        shutil.copytree(os.path.join(ROOT, "klar"), os.path.join(a.dir, "klar"), dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__"))
        what = "This is the implementation of Klar written in Python, in `klar/` (entry: `klar/cli.py`). Run it as `python -m klar check x.klar`."
    _, spec, _ = shell([sys.executable, "-m", "klar", "spec"], ROOT)
    with open(os.path.join(a.dir, "klar_spec.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(spec)
    with open(os.path.join(HERE, "b2_compiler", "task.md"), encoding="utf-8") as f:
        print(f"{what} The language as it is now is described in `klar_spec.md`.\n\n{f.read().strip()}\n\nHand the implementation in with `submit`. Hidden tests run its commands on Klar programs.")
    return 0


def cmd_submit(a):
    path = os.path.join(a.run, a.lang + ".json")
    st = {"attempts": [], "solved": False}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            st = json.load(f)
    if st["solved"]:
        print("This task is already solved.")
        return 0
    if len(st["attempts"]) >= a.attempts:
        print(f"No attempts left ({a.attempts}).")
        return 0
    r = evaluate(a.lang, a.dir)
    kinds = {c["name"]: c["kind"] for c in CHECKS}
    visible = [n for n in r["failed"] if kinds[n] == "visible"]
    held = [n for n in r["failed"] if kinds[n] == "holdout"]
    ok = r["stage"] == "checks" and not visible
    st["attempts"].append({"stage": r["stage"], "ok": ok, "visible_failed": visible, "holdout_failed": held})
    st["solved"] = ok
    os.makedirs(a.run, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    left = a.attempts - len(st["attempts"])
    if ok:
        print("PASSED.")
    elif left == 0:
        print("FAILED, no attempts left.")
    elif r["stage"] == "build":
        print(f"That did not work ({left} attempt(s) left). The build said:\n\n{r['feedback']}")
    else:
        lines = [f"FAIL  {n}\n      " + "\n      ".join(r["details"][n])[:700] for n in visible]
        print(f"That did not work ({left} attempt(s) left). The tests said:\n\n" + "\n".join(lines)[-6000:])
    return 0


def cmd_validate(a):
    r = evaluate(a.lang, a.dir)
    if r["stage"] == "build":
        print("build failed:\n" + r["feedback"])
        return 1
    for c in CHECKS:
        wrong = r["details"][c["name"]]
        print(f"{'FAIL' if wrong else 'ok  '} {c['kind']:8} {c['name']}")
        for w in wrong:
            print("       " + w[:600])
    print(f"{len(CHECKS) - len(r['failed'])} of {len(CHECKS)} pass")
    return 1 if r["failed"] else 0


def cmd_report(a):
    kinds = {c["name"]: c["kind"] for c in CHECKS}
    total = {k: sum(1 for v in kinds.values() if v == k) for k in ("visible", "holdout")}
    for lang in ("klar", "python"):
        path = os.path.join(a.run, lang + ".json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                st = json.load(f)
            for n, x in enumerate(st["attempts"], 1):
                print(f"{lang} attempt {n} ({x['stage']}): visible {len(x['visible_failed'])}/{total['visible']}, "
                      f"held-out {len(x['holdout_failed'])}/{total['holdout']}: {x['holdout_failed']}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("prompt", cmd_prompt), ("submit", cmd_submit), ("validate", cmd_validate)):
        p = sub.add_parser(name)
        p.add_argument("--lang", choices=("klar", "python"), required=True)
        p.add_argument("--dir", required=True)
        if name == "submit":
            p.add_argument("--run", required=True)
            p.add_argument("--attempts", type=int, default=3)
        p.set_defaults(fn=fn)
    p = sub.add_parser("report")
    p.add_argument("--run", required=True)
    p.set_defaults(fn=cmd_report)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
