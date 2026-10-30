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
import re
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


def languages(tid):
    """The languages a task is written in (the large task of refactor_big/ has no TypeScript)."""
    return [lang for lang in LANGS if os.path.isdir(os.path.join(TASKS, tid, lang))]


def sources(d, lang):
    return sorted(f for f in os.listdir(d) if f.endswith(EXT[lang]) and f != CHECK[lang])


KLAR_TEST_LIMIT = "100"     # `klar test --timeout`: as in llm_bench.py
FEEDBACK_CHARS = 6000       # one Klar failure shows its source and values, so 3000 would hide most of them


def run(cmd, cwd, timeout=120):
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                           env=dict(os.environ, PYTHONPATH=ROOT, NO_COLOR="1"))
        return p.returncode, (p.stdout + p.stderr).strip()
    except subprocess.TimeoutExpired:
        return -1, f"timeout after {timeout} s"


def evaluate(tid, lang, src_dir, with_tests=True, suite=None):
    """{"ok", "stage" ("compile" | "test" | "pass"), "feedback"} for the program in `src_dir`.

    `suite`: the file in tests/ to use instead of the one that answers the agent (a held-out suite)."""
    with tempfile.TemporaryDirectory() as d:
        for f in sources(src_dir, lang):
            shutil.copy(os.path.join(src_dir, f), os.path.join(d, f))
        if with_tests:
            shutil.copy(os.path.join(TASKS, tid, "tests", suite or CHECK[lang]), os.path.join(d, CHECK[lang]))
        if lang == "klar":
            files = [CHECK[lang]] if with_tests else sources(d, lang)
            for f in files:
                code, out = run([sys.executable, "-m", "klar", "check", f], d)
                if code != 0:
                    return {"ok": False, "stage": "compile", "feedback": out[-FEEDBACK_CHARS:]}
            if not with_tests:
                return {"ok": True, "stage": "pass", "feedback": ""}
            code, out = run([sys.executable, "-m", "klar", "test", "--timeout", KLAR_TEST_LIMIT, CHECK[lang]], d)
            return {"ok": code == 0, "stage": "pass" if code == 0 else "test", "feedback": "" if code == 0 else
                    out[-FEEDBACK_CHARS:], "output": out}
        if lang == "python":
            if not with_tests:
                for f in sources(d, lang):
                    code, out = run([sys.executable, "-m", "py_compile", f], d)
                    if code != 0:
                        return {"ok": False, "stage": "compile", "feedback": out[-FEEDBACK_CHARS:]}
                return {"ok": True, "stage": "pass", "feedback": ""}
            code, out = run([sys.executable, CHECK[lang]], d)
            if code == 0:
                return {"ok": True, "stage": "pass", "feedback": ""}
            stage = "compile" if "SyntaxError" in out or "IndentationError" in out else "test"
            return {"ok": False, "stage": stage, "feedback": out[-FEEDBACK_CHARS:], "output": out}
        tsc = shutil.which("tsc")
        if tsc is None:
            raise SystemExit("TypeScript needs `tsc` (npm install -g typescript)")
        files = sources(d, lang) + ([CHECK[lang]] if with_tests else [])
        code, out = run([tsc, "--strict", "--target", "es2020", "--module", "commonjs", "--outDir", "out", *files], d)
        if code != 0:
            return {"ok": False, "stage": "compile", "feedback": out[-FEEDBACK_CHARS:]}
        if not with_tests:
            return {"ok": True, "stage": "pass", "feedback": ""}
        code, out = run(["node", os.path.join("out", "check.js")], d)
        return {"ok": code == 0, "stage": "pass" if code == 0 else "test", "feedback": "" if code == 0 else out[-FEEDBACK_CHARS:]}


def holdout_file(tid, lang):
    """The held-out suite of a task: it never answers the agent and says what would have shipped."""
    path = os.path.join(TASKS, tid, "tests", "holdout" + EXT[lang])
    return os.path.basename(path) if os.path.exists(path) else None


def suite_size(tid, lang, name):
    with open(os.path.join(TASKS, tid, "tests", name), encoding="utf-8") as f:
        text = f.read()
    return text.count('\ntest "') if lang == "klar" else text.count('\nrun("')


def failures(result, tid, lang, name):
    """How many checks of a suite failed: all of them when the suite did not compile against the program."""
    if result["ok"]:
        return 0
    found = re.search(r"(\d+) passed, (\d+) failed", result["feedback"])
    return int(found.group(2)) if found and result["stage"] == "test" else suite_size(tid, lang, name)


def failed_names(result):
    return re.findall(r"(?m)^\s*FAIL\s+(.+?)\s*$", result.get("output", ""))


def run_main(lang, d):
    cmd = [sys.executable, "-m", "klar", "run", "main.klar"] if lang == "klar" else [sys.executable, "main.py"]
    return run(cmd, d)


def same_output(tid, lang, src_dir):
    """True when the program's own `main` prints what the reference prints."""
    with tempfile.TemporaryDirectory() as d:
        for f in sources(os.path.join(TASKS, tid, lang), lang):
            shutil.copy(os.path.join(TASKS, tid, lang, f), os.path.join(d, f))
        ref = os.path.join(TASKS, tid, "ref", lang)
        for f in sources(ref, lang):
            shutil.copy(os.path.join(ref, f), os.path.join(d, f))
        expected = run_main(lang, d)
    return run_main(lang, src_dir) == expected


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
    attempt = {"files": files, "stage": result["stage"], "ok": result["ok"]}
    held_out = holdout_file(a.id, a.lang)
    if held_out:
        attempt["failed"] = failures(result, a.id, a.lang, CHECK[a.lang])
        secret = evaluate(a.id, a.lang, a.dir, suite=held_out)
        attempt["holdout_failed"] = failures(secret, a.id, a.lang, held_out)
        attempt["failed_names"] = failed_names(result)
        attempt["holdout_names"] = failed_names(secret)
        attempt["same_output"] = same_output(a.id, a.lang, a.dir)
    st["attempts"].append(attempt)
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
        for lang in languages(tid):
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
                held_out = holdout_file(tid, lang)
                r3 = evaluate(tid, lang, d, suite=held_out) if held_out else r2
                if not r3["ok"]:
                    print("    " + r3["feedback"][:1500].replace("\n", "\n    "))
            ok = r0["ok"] and not r1["ok"] and r2["ok"] and r3["ok"]
            bad += not ok
            print(f"{'ok ' if ok else 'BAD'} {tid:24} {lang:10} original compiles: {r0['ok']}, its tests fail: "
                  f"{not r1['ok']} ({r1['stage']}), reference passes: {r2['ok']}, held-out suite: {r3['ok']}")
            if not r0["ok"]:
                print("    " + r0["feedback"][:1500].replace("\n", "\n    "))
            if not r2["ok"]:
                print("    " + r2["feedback"][:1500].replace("\n", "\n    "))
    return 1 if bad else 0


def cmd_report(a):
    rows = []
    big = []
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
            for x in st["attempts"]:
                if "holdout_failed" in x:
                    big.append(f"| {tid} | {lang} | {x['stage']} | {x['failed']}/{suite_size(tid, lang, CHECK[lang])} | "
                               f"{x['holdout_failed']}/{suite_size(tid, lang, holdout_file(tid, lang))} | "
                               f"{x['same_output']} |")
        rows.append(f"| {lang} | {n} | {first} | {solved} | {comp} | {test} |")
    print("| language | tasks | first try | solved | failed: compile | failed: tests |\n|---|---:|---:|---:|---:|---:|")
    print("\n".join(rows))
    if big:
        print("\n| task | language | attempt ended at | visible checks failed | held-out checks failed | main prints the "
              "same |\n|---|---|---|---:|---:|---|")
        print("\n".join(big))
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
