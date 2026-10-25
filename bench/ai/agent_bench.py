#!/usr/bin/env python3
"""The LLM benchmark with agents as the model (ROADMAP item 20): an agent (for example a Claude Code subagent of a
given model) gets a task only through `prompt`, hands in a file only through `submit`, and sees exactly what
llm_bench.py would show a model: the same prompt, the same hidden tests, the same feedback, at most --attempts tries.
Every attempt is recorded; `score` turns the run into llm_bench.py's answers.json and scores it with
`--provider replay`, so the numbers come from the same code as for a model behind an API.

    python bench/ai/agent_bench.py prompt --suite humaneval --lang klar --id he_0_has_close_elements
    python bench/ai/agent_bench.py submit --run R --suite humaneval --lang klar --id he_0_has_close_elements --file f.klar
    python bench/ai/agent_bench.py score --run R --suite humaneval
    python bench/ai/agent_bench.py report --root RUNS --out report.md   # every model, suite and language

The agents work one language each (an agent that solved a task in Python would only translate it), and are told not
to run compilers or tests themselves: `submit` is their only feedback, as for a model. The Klar reference
(`klar spec`) is a file the agent reads once instead of a prefix of every prompt.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import llm_bench as B  # noqa: E402

SPEC_NOTE = "The Klar language reference is in the file `klar_spec.md` next to you: read it before the first task."


def task_of(suite, tid):
    path, _ = B.SUITES[suite]
    with open(path, encoding="utf-8") as f:
        for t in json.load(f):
            if t["id"] == tid:
                return t
    raise SystemExit(f"no task {tid} in {suite}")


def the_prompt(task, lang):
    text = B.prompt(task, lang, "").replace("Language reference:\n\n\n\n", "")
    if lang == "klar":
        text = SPEC_NOTE + "\n\n" + text
    return text.replace("Reply with the complete file in one code block and nothing else.",
                        f"Write the complete file `solution.{B.EXT[lang]}` and hand it in with `submit`.")


def state_path(run, suite, lang, tid):
    return os.path.join(run, suite, lang, tid + ".json")


def load_state(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {"attempts": [], "solved": False}


def cmd_prompt(a):
    print(the_prompt(task_of(a.suite, a.id), a.lang))
    return 0


def cmd_submit(a):
    task = task_of(a.suite, a.id)
    path = state_path(a.run, a.suite, a.lang, a.id)
    st = load_state(path)
    if st["solved"]:
        print("This task is already solved. Move on to the next one.")
        return 0
    if len(st["attempts"]) >= a.attempts:
        print(f"No attempts left ({a.attempts}). Move on to the next one.")
        return 0
    with open(a.file, encoding="utf-8") as f:
        code = f.read()
    result = B.evaluate(task, a.lang, code)
    st["attempts"].append({"code": code, "stage": result["stage"], "ok": result["ok"]})
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
              "Fix the file and submit it again.")
    return 0


def cmd_score(a):
    root = os.path.join(a.run, a.suite)
    answers = {}
    langs = []
    for lang in B.LANGS:
        d = os.path.join(root, lang)
        if not os.path.isdir(d):
            continue
        langs.append(lang)
        for name in sorted(os.listdir(d)):
            tid = name[:-5]
            st = load_state(os.path.join(d, name))
            for k, att in enumerate(st["attempts"]):
                answers[f"{tid}/{lang}/{k}"] = {"text": "```\n" + att["code"] + "```", "in": 0, "out": 0}
    with open(os.path.join(root, "answers.json"), "w", encoding="utf-8") as f:
        json.dump(answers, f, ensure_ascii=False, indent=1)
    ids = sorted({k.split("/")[0] for k in answers})
    path, _ = B.SUITES[a.suite]
    with open(path, encoding="utf-8") as f:
        all_ids = [t["id"] for t in json.load(f)]
    missing = [t for t in all_ids if t not in ids]
    if missing:
        print(f"note: {len(missing)} task(s) have no attempt (e.g. {missing[0]}): they count as not solved",
              file=sys.stderr)
    name = a.name or os.path.basename(os.path.normpath(a.run))
    argv = ["--suite", a.suite, "--provider", "replay", "--replay", root, "--name", name, "-l", *langs,
            "--attempts", str(a.attempts)]
    code = B.main(argv)
    # the replay is the result: every attempt evaluated again, one after the other on a quiet machine (an
    # evaluation during the run can time out when many agents submit at once); its outcomes go back to the records
    full = name if a.suite == "own" else f"{a.suite}-{name}"
    with open(os.path.join(HERE, "results", B.re.sub(r"[^A-Za-z0-9._-]", "_", full), "report.json"),
              encoding="utf-8") as f:
        records = json.load(f)["records"]
    changed = 0
    for rec in records:
        path = state_path(a.run, a.suite, rec["lang"], rec["task"])
        st = load_state(path)
        if not st["attempts"]:
            continue
        stages = [x["stage"] for x in rec["attempts"]]
        new = [dict(att, stage=stage, ok=stage == "pass") for att, stage in zip(st["attempts"], stages)]
        if new != st["attempts"] or st["solved"] != rec["solved"]:
            changed += 1
        st["attempts"], st["solved"] = new, rec["solved"]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=1)
    print(f"score: {changed} record(s) differ from the evaluation during the run (updated)", file=sys.stderr)
    return code


def wilson(k, n, z=1.96):
    """The 95% Wilson interval of k successes out of n, in percent."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return (100 * max(0.0, c - h), 100 * min(1.0, c + h))


def mcnemar(a, b):
    """Exact two-sided McNemar test on paired outcomes (dict task -> bool): (a only, b only, p)."""
    from math import comb
    only_a = sum(1 for t in a if t in b and a[t] and not b[t])
    only_b = sum(1 for t in a if t in b and b[t] and not a[t])
    n = only_a + only_b
    if n == 0:
        return only_a, only_b, 1.0
    k = min(only_a, only_b)
    p = min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n)
    return only_a, only_b, p


def cmd_report(a):
    """All runs under --root (<model>/<suite>/<lang>/<task>.json) as one Markdown report."""
    rows, pairs = [], []
    for model in sorted(m for m in os.listdir(a.root) if os.path.isdir(os.path.join(a.root, m))):
        for suite in sorted(os.listdir(os.path.join(a.root, model))):
            first, solved = {}, {}
            for lang in B.LANGS:
                d = os.path.join(a.root, model, suite, lang)
                if not os.path.isdir(d):
                    continue
                n = k1 = ks = comp = test = 0
                first[lang], solved[lang] = {}, {}
                for name in sorted(os.listdir(d)):
                    st = load_state(os.path.join(d, name))
                    if not st["attempts"]:
                        continue
                    n += 1
                    one = st["attempts"][0]["ok"]
                    k1 += one
                    ks += st["solved"]
                    first[lang][name] = one
                    solved[lang][name] = st["solved"]
                    for att in st["attempts"]:
                        if not att["ok"]:
                            comp += att["stage"] == "compile"
                            test += att["stage"] == "test"
                lo, hi = wilson(k1, n)
                rows.append(f"| {model} | {suite} | {B.NAMES[lang]} | {n} | {k1} ({100 * k1 / max(n, 1):.1f}%, "
                            f"{lo:.1f}–{hi:.1f}) | {ks} ({100 * ks / max(n, 1):.1f}%) | {comp} | {test} |")
            for other in ("python", "typescript"):
                if "klar" in first and other in first:
                    x, y, p = mcnemar(first["klar"], first[other])
                    pairs.append(f"| {model} | {suite} | Klar vs {B.NAMES[other]} | {x} | {y} | {p:.3f} |")
    # everything together: success, attempts, understanding of the language, effort (usage.json, when present)
    usage = {}
    upath = os.path.join(a.root, "usage.json")
    if os.path.exists(upath):
        with open(upath, encoding="utf-8") as f:
            usage = json.load(f)
    combined = []
    for model in sorted(m for m in os.listdir(a.root) if os.path.isdir(os.path.join(a.root, m))):
        for suite in sorted(os.listdir(os.path.join(a.root, model))):
            for lang in B.LANGS:
                d = os.path.join(a.root, model, suite, lang)
                if not os.path.isdir(d):
                    continue
                sts = [load_state(os.path.join(d, n)) for n in sorted(os.listdir(d))]
                sts = [st for st in sts if st["attempts"]]
                n = len(sts)
                if n == 0:
                    continue
                tries = sum(len(st["attempts"]) for st in sts)
                to_solve = [len(st["attempts"]) for st in sts if st["solved"]]
                lang_err = sum(1 for st in sts if st["attempts"][0]["stage"] == "compile")
                u = usage.get(model, {}).get(suite, {}).get(lang)
                tok = f"{sum(x[0] for x in u) / n:,.0f}" if u else "—"
                sec = f"{sum(x[2] for x in u) / n / 1000:.1f}" if u else "—"
                calls = f"{sum(x[1] for x in u) / n:.2f}" if u else "—"
                combined.append(f"| {model} | {suite} | {B.NAMES[lang]} | {100 * sum(st['attempts'][0]['ok'] for st in sts) / n:.1f}% | "
                                f"{100 * sum(st['solved'] for st in sts) / n:.1f}% | {tries / n:.3f} | "
                                f"{sum(to_solve) / max(len(to_solve), 1):.3f} | {lang_err} ({100 * lang_err / n:.1f}%) | "
                                f"{tok} | {calls} | {sec} |")
    text = ("# LLM benchmark with agents as the model\n\n"
            "Generated by `bench/ai/agent_bench.py report`. Each agent worked in one language, got the tasks only "
            "through `prompt`, handed in files only through `submit` (at most 3 attempts, the feedback of "
            "llm_bench.py), and did not run compilers or tests itself.\n\n"
            "| model | suite | language | tasks | first try (95% CI) | solved | failed attempts: compile | test |\n"
            "|---|---|---|---:|---|---:|---:|---:|\n" + "\n".join(rows) + "\n\n"
            "First try, paired by task (exact McNemar test): tasks only the first language solved on the first "
            "try, only the second, and the p-value of the difference.\n\n"
            "| model | suite | pair | only Klar | only the other | p |\n|---|---|---|---:|---:|---:|\n"
            + "\n".join(pairs) + "\n\n"
            "## Everything together\n\n"
            "Per task: solved on the first try and in the end; attempts handed in; attempts until solved (of the "
            "solved ones); first attempts the compiler rejected (the model did not write valid code of the language "
            "— how well it understands it); the agent's tokens (with reading the reference once) and tool calls; "
            "wall-clock seconds (with the harness: `tsc` is slow, Python fast; on a busy machine).\n\n"
            "| model | suite | language | first try | solved | attempts | attempts to solve | first attempt "
            "rejected by the compiler | tokens | tool calls | seconds |\n"
            "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|\n" + "\n".join(combined) + "\n")
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
    print(text)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prompt")
    p.add_argument("--suite", choices=sorted(B.SUITES), default="humaneval")
    p.add_argument("--lang", choices=B.LANGS, required=True)
    p.add_argument("--id", required=True)
    p.set_defaults(fn=cmd_prompt)
    p = sub.add_parser("submit")
    p.add_argument("--run", required=True, help="the directory of this run")
    p.add_argument("--suite", choices=sorted(B.SUITES), default="humaneval")
    p.add_argument("--lang", choices=B.LANGS, required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--file", required=True)
    p.add_argument("--attempts", type=int, default=3)
    p.set_defaults(fn=cmd_submit)
    p = sub.add_parser("score")
    p.add_argument("--run", required=True)
    p.add_argument("--suite", choices=sorted(B.SUITES), default="humaneval")
    p.add_argument("--attempts", type=int, default=3)
    p.add_argument("--name")
    p.set_defaults(fn=cmd_score)
    p = sub.add_parser("report")
    p.add_argument("--root", required=True, help="the directory with <model>/<suite>/<lang>/ runs")
    p.add_argument("--out", help="write the report here too")
    p.set_defaults(fn=cmd_report)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
