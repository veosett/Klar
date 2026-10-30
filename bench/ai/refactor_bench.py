#!/usr/bin/env python3
"""Refactoring benchmark: an agent changes an existing program of several modules, as in real work.

    python bench/ai/refactor_bench.py validate                       # every task, every language
    python bench/ai/refactor_bench.py prompt --id R --lang klar --dir WORK
    python bench/ai/refactor_bench.py submit --run RUN --id R --lang klar --dir WORK
    python bench/ai/refactor_bench.py report --run RUN

Each task (bench/ai/refactor/<id>/) is one program written three times, in Klar, Python and TypeScript
(`klar/`, `python/`, `typescript/`: the same modules, functions and behaviour), a change request (`task.md`), hidden
tests of the changed program (`tests/check.klar`, `check.py`, `check.ts`) and a reference change (`ref/<lang>/`,
the files that differ). The change touches several places in several modules; the thesis under test is that a
compiler which knows every place (types, exhaustive matches) gets the agent to a correct program in fewer attempts
than tests alone.

`prompt` copies the original program into WORK and prints the request; `submit` runs the hidden tests on the
files in WORK, the way an agent's tool would (Klar: `klar test`; Python: the interpreter; TypeScript:
`tsc --strict`, then node), records the attempt and prints the feedback. At most --attempts attempts.
`validate` checks the suite: the original programs compile, their hidden tests fail, the references pass.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
TASKS = os.environ.get("KLAR_REFACTOR_TASKS") or os.path.join(HERE, "refactor")
LANGS = ("klar", "python", "typescript")
EXT = {"klar": ".klar", "python": ".py", "typescript": ".ts"}
CHECK = {"klar": "check.klar", "python": "check.py", "typescript": "check.ts"}


def task_ids():
    return sorted(d for d in os.listdir(TASKS) if os.path.isfile(os.path.join(TASKS, d, "task.md")))


def sources(d, lang):
    return sorted(f for f in os.listdir(d) if f.endswith(EXT[lang]) and f != CHECK[lang])


KLAR_TEST_LIMIT = "100"     # `klar test --timeout`: as in llm_bench.py


def run(cmd, cwd, timeout=120):
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                           env=dict(os.environ, PYTHONPATH=ROOT, NO_COLOR="1"))
        return p.returncode, (p.stdout + p.stderr).strip()
    except subprocess.TimeoutExpired:
        return -1, f"timeout after {timeout} s"


def evaluate(tid, lang, src_dir, with_tests=True):
    """{"ok", "stage" ("compile" | "test" | "pass"), "feedback"} for the program in `src_dir`."""
    with tempfile.TemporaryDirectory() as d:
        for f in sources(src_dir, lang):
            shutil.copy(os.path.join(src_dir, f), os.path.join(d, f))
        if with_tests:
            shutil.copy(os.path.join(TASKS, tid, "tests", CHECK[lang]), os.path.join(d, CHECK[lang]))
        if lang == "klar":
            files = [CHECK[lang]] if with_tests else sources(d, lang)
            for f in files:
                code, out = run([sys.executable, "-m", "klar", "check", f], d)
                if code != 0:
                    return {"ok": False, "stage": "compile", "feedback": out[-3000:]}
            if not with_tests:
                return {"ok": True, "stage": "pass", "feedback": ""}
            code, out = run([sys.executable, "-m", "klar", "test", "--timeout", KLAR_TEST_LIMIT, CHECK[lang]], d)
            return {"ok": code == 0, "stage": "pass" if code == 0 else "test", "feedback": "" if code == 0 else
                    out[-3000:]}
        if lang == "python":
            if not with_tests:
                for f in sources(d, lang):
                    code, out = run([sys.executable, "-m", "py_compile", f], d)
                    if code != 0:
                        return {"ok": False, "stage": "compile", "feedback": out[-3000:]}
                return {"ok": True, "stage": "pass", "feedback": ""}
            code, out = run([sys.executable, CHECK[lang]], d)
            if code == 0:
                return {"ok": True, "stage": "pass", "feedback": ""}
            stage = "compile" if "SyntaxError" in out or "IndentationError" in out else "test"
            return {"ok": False, "stage": stage, "feedback": out[-3000:]}
        tsc = shutil.which("tsc")
        if tsc is None:
            raise SystemExit("TypeScript needs `tsc` (npm install -g typescript)")
        files = sources(d, lang) + ([CHECK[lang]] if with_tests else [])
        code, out = run([tsc, "--strict", "--target", "es2020", "--module", "commonjs", "--outDir", "out", *files], d)
        if code != 0:
            return {"ok": False, "stage": "compile", "feedback": out[-3000:]}
        if not with_tests:
            return {"ok": True, "stage": "pass", "feedback": ""}
        code, out = run(["node", os.path.join("out", "check.js")], d)
        return {"ok": code == 0, "stage": "pass" if code == 0 else "test", "feedback": "" if code == 0 else out[-3000:]}


def statement(tid, lang):
    with open(os.path.join(TASKS, tid, "task.md"), encoding="utf-8") as f:
        text = f.read().strip()
    names = {"klar": "Klar", "python": "Python 3", "typescript": "TypeScript (strict)"}
    files = ", ".join(f"`{f}`" for f in sources(os.path.join(TASKS, tid, lang), lang))
    note = ("The Klar language reference is in the file `klar_spec.md` next to you: read it before the first task.\n\n"
            if lang == "klar" else "")
    return (f"{note}The {names[lang]} program in your working directory ({files}) needs a change.\n\n{text}\n\n"
            "Edit the files in place (keep the module and function names unless the change says otherwise), then "
            "hand the program in with `submit`. Hidden tests check the changed program.")


def state_path(run_dir, tid, lang):
    return os.path.join(run_dir, tid, lang + ".json")


def load_state(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {"attempts": [], "solved": False}


def cmd_prompt(a):
    src = os.path.join(TASKS, a.id, a.lang)
    os.makedirs(a.dir, exist_ok=True)
    for f in sources(src, a.lang):
        shutil.copy(os.path.join(src, f), os.path.join(a.dir, f))
    print(statement(a.id, a.lang))
    return 0


def cmd_submit(a):
    path = state_path(a.run, a.id, a.lang)
    st = load_state(path)
    if st["solved"]:
        print("This task is already solved. Move on to the next one.")
        return 0
    if len(st["attempts"]) >= a.attempts:
        print(f"No attempts left ({a.attempts}). Move on to the next one.")
        return 0
    result = evaluate(a.id, a.lang, a.dir)
    files = {}
    for f in sources(a.dir, a.lang):
        with open(os.path.join(a.dir, f), encoding="utf-8") as fh:
            files[f] = fh.read()
    st["attempts"].append({"files": files, "stage": result["stage"], "ok": result["ok"]})
    st["solved"] = result["ok"]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    left = a.attempts - len(st["attempts"])
    if result["ok"]:
        print("PASSED. Move on to the next task.")
    elif left == 0:
        print("FAILED, no attempts left. Move on to the next task.")
    else:
        what = "The compiler said:" if result["stage"] == "compile" else "The tests said:"
        print(f"That did not work ({left} attempt(s) left). {what}\n\n{result['feedback']}\n\n"
              "Fix the program and submit it again.")
    return 0


def cmd_validate(a):
    bad = 0
    for tid in task_ids():
        for lang in LANGS:
            orig = os.path.join(TASKS, tid, lang)
            r0 = evaluate(tid, lang, orig, with_tests=False)
            r1 = evaluate(tid, lang, orig)
            with tempfile.TemporaryDirectory() as d:
                for f in sources(orig, lang):
                    shutil.copy(os.path.join(orig, f), os.path.join(d, f))
                ref = os.path.join(TASKS, tid, "ref", lang)
                for f in sources(ref, lang):
                    shutil.copy(os.path.join(ref, f), os.path.join(d, f))
                r2 = evaluate(tid, lang, d)
            ok = r0["ok"] and not r1["ok"] and r2["ok"]
            bad += not ok
            print(f"{'ok ' if ok else 'BAD'} {tid:24} {lang:10} original compiles: {r0['ok']}, its tests fail: "
                  f"{not r1['ok']} ({r1['stage']}), reference passes: {r2['ok']}")
            if not r0["ok"]:
                print("    " + r0["feedback"][:1500].replace("\n", "\n    "))
            if not r2["ok"]:
                print("    " + r2["feedback"][:1500].replace("\n", "\n    "))
    return 1 if bad else 0


def cmd_report(a):
    rows = []
    for lang in LANGS:
        n = first = solved = comp = test = 0
        for tid in task_ids():
            st = load_state(state_path(a.run, tid, lang))
            if not st["attempts"]:
                continue
            n += 1
            first += st["attempts"][0]["ok"]
            solved += st["solved"]
            comp += sum(1 for x in st["attempts"] if x["stage"] == "compile")
            test += sum(1 for x in st["attempts"] if x["stage"] == "test")
        rows.append(f"| {lang} | {n} | {first} | {solved} | {comp} | {test} |")
    print("| language | tasks | first try | solved | failed: compile | failed: tests |\n|---|---:|---:|---:|---:|---:|")
    print("\n".join(rows))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prompt")
    p.add_argument("--id", required=True)
    p.add_argument("--lang", choices=LANGS, required=True)
    p.add_argument("--dir", required=True)
    p.set_defaults(fn=cmd_prompt)
    p = sub.add_parser("submit")
    p.add_argument("--run", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--lang", choices=LANGS, required=True)
    p.add_argument("--dir", required=True)
    p.add_argument("--attempts", type=int, default=3)
    p.set_defaults(fn=cmd_submit)
    p = sub.add_parser("validate")
    p.set_defaults(fn=cmd_validate)
    p = sub.add_parser("report")
    p.add_argument("--run", required=True)
    p.set_defaults(fn=cmd_report)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
