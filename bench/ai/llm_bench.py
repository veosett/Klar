#!/usr/bin/env python3
"""LLM benchmark: how well does a language model write working code in Klar, compared with Python and TypeScript?

    python bench/ai/llm_bench.py --model claude-sonnet-4-5            # Anthropic API (ANTHROPIC_API_KEY)
    python bench/ai/llm_bench.py --provider openai --model gpt-4.1     # OpenAI-compatible (OPENAI_API_KEY,
                                                                      #   OPENAI_BASE_URL for other servers)
    python bench/ai/llm_bench.py --provider reference                 # the reference solutions: checks the suite
    python bench/ai/llm_bench.py --provider replay --replay results/x  # re-score saved answers, no API calls

Every task in tasks/tasks.json is one function with a statement, typed parameters and hidden test cases. For each
language the model gets the statement and the signature (for Klar also the language reference, `klar spec`, since
models have seen little Klar), writes the file, and the harness runs the hidden tests the way an agent would:
Klar with `klar test` (type check + tests), Python with the interpreter, TypeScript with `tsc --strict` + node.
On failure the model sees the compiler messages and the failing cases and tries again, up to --attempts times.

Measured per language: tasks solved on the first attempt and in total, attempts and tokens used, how many failures
the compiler caught before running (compile errors) versus failures only the tests found (wrong results, crashes).
Answers are saved (results/<name>/answers.json) so a run can be re-scored with --provider replay.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
TASKS = os.path.join(HERE, "tasks", "tasks.json")
REFS = os.path.join(HERE, "tasks", "ref")
# outside suites (bench/ai/build_suites.py): HumanEval and MBPP from MultiPL-E, the same tests in every language
SUITES = {"own": (TASKS, REFS)}
for _name in ("humaneval", "mbpp", "humaneval_plus"):
    SUITES[_name] = (os.path.join(HERE, "suites", _name, "tasks.json"), os.path.join(HERE, "suites", _name, "ref"))
LANGS = ("klar", "python", "typescript")
EXT = {"klar": "klar", "python": "py", "typescript": "ts"}


# ---- types: parse "Map[Str, Int]" ---------------------------------------------------------------------------------
def parse_type(t):
    t = t.strip()
    if "[" not in t:
        return (t, [])
    head, inner = t[:t.index("[")], t[t.index("[") + 1:-1]
    args, depth, cur = [], 0, ""
    for c in inner:
        if c == "," and depth == 0:
            args.append(cur)
            cur = ""
            continue
        depth += c == "["
        depth -= c == "]"
        cur += c
    args.append(cur)
    return (head, [parse_type(a) for a in args])


def show_klar_type(t):
    return t[0] + ("[" + ", ".join(show_klar_type(a) for a in t[1]) + "]" if t[1] else "")


def py_type(t):
    h, a = t
    return {"Int": "int", "Float": "float", "Str": "str", "Bool": "bool"}.get(h) or {
        "List": lambda: f"list[{py_type(a[0])}]", "Map": lambda: f"dict[{py_type(a[0])}, {py_type(a[1])}]",
        "Option": lambda: f"{py_type(a[0])} | None", "Result": lambda: py_type(a[0]),
        "Pair": lambda: f"tuple[{py_type(a[0])}, {py_type(a[1])}]"}[h]()


def ts_type(t):
    h, a = t
    return {"Int": "number", "Float": "number", "Str": "string", "Bool": "boolean"}.get(h) or {
        "List": lambda: f"{ts_type(a[0])}[]", "Map": lambda: f"Record<{ts_type(a[0])}, {ts_type(a[1])}>",
        "Option": lambda: f"{ts_type(a[0])} | null", "Result": lambda: ts_type(a[0]),
        "Pair": lambda: f"[{ts_type(a[0])}, {ts_type(a[1])}]"}[h]()


# ---- values as literals ----------------------------------------------------------------------------------------------
def klar_str(s):
    """A Klar string literal; other control characters (Klar has escapes for \\n, \\t, \\r and \\0) are joined in
    as `(13).to_char().unwrap_or("")`."""
    parts, cur = [], ""
    for c in s:
        if ord(c) < 32 and c not in "\n\t\r\0":
            parts += ['"' + cur + '"', f'({ord(c)}).to_char().unwrap_or("")']
            cur = ""
            continue
        cur += {"\\": "\\\\", '"': '\\"', "{": "\\{", "}": "\\}", "\n": "\\n", "\t": "\\t", "\r": "\\r", "\0": "\\0"}.get(c, c)
    parts.append('"' + cur + '"')
    return parts[0] if len(parts) == 1 else "(" + " + ".join(p for p in parts if p != '""') + ")"


def klar_float(v):
    """A Klar Float literal: digits and a point, no exponent (`1e-05` is `0.00001`)."""
    from decimal import Decimal
    text = format(Decimal(repr(float(v))), "f")
    return text if "." in text else text + ".0"


def klar_lit(v, t):
    h, a = t
    if h == "Int":
        return str(v)
    if h == "Float":
        return klar_float(v)
    if h == "Bool":
        return "true" if v else "false"
    if h == "Str":
        return klar_str(v)
    if h == "List":
        return "[" + ", ".join(klar_lit(x, a[0]) for x in v) + "]"
    if h == "Map":
        return "Map {" + ", ".join(f"{klar_lit(k, a[0])}: {klar_lit(x, a[1])}" for k, x in v.items()) + "}"
    if h == "Option":
        return "None" if v is None else f"Some({klar_lit(v, a[0])})"
    if h == "Result":
        return f"Ok({klar_lit(v['ok'], a[0])})" if "ok" in v else f"Err({klar_lit(v['err'], a[1])})"
    if h == "Pair":
        return f"Pair {{ first: {klar_lit(v[0], a[0])}, second: {klar_lit(v[1], a[1])} }}"
    raise ValueError(h)


def py_lit(v, t):
    if t[0] == "Float":
        return repr(float(v))
    if t[0] == "List":
        return "[" + ", ".join(py_lit(x, t[1][0]) for x in v) + "]"
    if t[0] == "Map":
        return "{" + ", ".join(f"{py_lit(k, t[1][0])}: {py_lit(x, t[1][1])}" for k, x in v.items()) + "}"
    if t[0] == "Option":
        return "None" if v is None else py_lit(v, t[1][0])
    if t[0] == "Pair":
        return f"({py_lit(v[0], t[1][0])}, {py_lit(v[1], t[1][1])})"
    return repr(v)


# ---- the task as the model sees it -------------------------------------------------------------------------------------
def signature(task, lang):
    params = [(n, parse_type(t)) for n, t in task["params"]]
    ret = parse_type(task["ret"])
    if lang == "klar":
        return f"pub fn {task['fn']}({', '.join(n + ': ' + show_klar_type(t) for n, t in params)}) -> " \
               f"{show_klar_type(ret)}"
    if lang == "python":
        return f"def {task['fn']}({', '.join(n + ': ' + py_type(t) for n, t in params)}) -> {py_type(ret)}:"
    return f"export function {task['fn']}({', '.join(n + ': ' + ts_type(t) for n, t in params)}): {ts_type(ret)}"


ERRORS = {
    "klar": "Errors are values: the function returns `Err(\"message\")` / `Ok(value)` as its type says.",
    "python": "Where the task says \"fail with M\", raise ValueError(M) (the message must be exactly M).",
    "typescript": "Where the task says \"fail with M\", throw new Error(M) (the message must be exactly M).",
}
NAMES = {"klar": "Klar", "python": "Python 3", "typescript": "TypeScript (strict)"}


def prompt(task, lang, spec):
    examples = "\n".join(f"- {task['fn']}({', '.join(json.dumps(x, ensure_ascii=False) for x in args)}) -> "
                         f"{json.dumps(want, ensure_ascii=False)}" for args, want in task["tests"][:2])
    head = f"Language reference:\n\n{spec}\n\n" if lang == "klar" else ""
    return (f"{head}Write a {NAMES[lang]} file `solution.{EXT[lang]}` that defines this function:\n\n"
            f"    {signature(task, lang)}\n\n{task['statement']}\n{ERRORS[lang]}\n\n"
            f"Examples (JSON notation; for results {{\"ok\": v}} / {{\"err\": message}}, null = no value):\n{examples}\n\n"
            "Reply with the complete file in one code block and nothing else.")


def extract_code(text):
    blocks = re.findall(r"```[a-zA-Z]*\n(.*?)```", text, re.S)
    return (max(blocks, key=len) if blocks else text).strip() + "\n"


# ---- running the hidden tests ------------------------------------------------------------------------------------------
def tests_klar(task):
    ret = parse_type(task["ret"])
    params = [parse_type(t) for _, t in task["params"]]
    out = [f"use solution.{{{task['fn']}}}", ""]
    for i, (args, want) in enumerate(task["tests"]):
        lits = [klar_lit(a, t) for a, t in zip(args, params)]
        if len(lits) >= 3:      # Klar names the arguments of a call with three or more
            lits = [f"{n}: {x}" for (n, _), x in zip(task["params"], lits)]
        call = f"{task['fn']}({', '.join(lits)})"
        out += [f"test {klar_str(f'case {i + 1}: {call}')} {{",
                f"  assert {call} == {klar_lit(want, ret)}", "}", ""]
    return "\n".join(out)


def tests_python(task):
    ret = parse_type(task["ret"])
    params = [parse_type(t) for _, t in task["params"]]
    cases = []
    for args, want in task["tests"]:
        call = f"{task['fn']}({', '.join(py_lit(a, t) for a, t in zip(args, params))})"
        if ret[0] == "Result":
            kind, val = ("ok", py_lit(want["ok"], ret[1][0])) if "ok" in want else ("err", repr(want["err"]))
        else:
            kind, val = "ok", py_lit(want, ret)
        cases.append(f"    ({call!r}, lambda: {call}, {kind!r}, {val}),")
    return "\n".join([
        f"from solution import {task['fn']}", "", "CASES = [", *cases, "]", "",
        "failed = 0",
        "for i, (text, run, kind, want) in enumerate(CASES, 1):",
        "    try:",
        "        got = run()",
        "    except Exception as ex:  # noqa: BLE001",
        "        if kind == 'err' and str(ex) == want:",
        "            continue",
        "        failed += 1",
        "        print(f'FAIL case {i}: {text} raised {type(ex).__name__}: {ex}; expected ' +",
        "              (f'the error {want!r}' if kind == 'err' else repr(want)))",
        "        continue",
        "    if kind == 'err' or got != want:",
        "        failed += 1",
        "        print(f'FAIL case {i}: {text} returned {got!r}; expected ' +",
        "              (f'the error {want!r}' if kind == 'err' else repr(want)))",
        "print(f'{len(CASES) - failed} passed, {failed} failed')",
        "raise SystemExit(1 if failed else 0)", ""])


def tests_typescript(task):
    ret = parse_type(task["ret"])
    cases = []
    for args, want in task["tests"]:
        call = f"{task['fn']}({', '.join(json.dumps(a, ensure_ascii=False) for a in args)})"
        if ret[0] == "Result":
            kind, val = ("ok", want["ok"]) if "ok" in want else ("err", want["err"])
        else:
            kind, val = "ok", want
        cases.append(f"  [{json.dumps(call)}, () => {call}, {json.dumps(kind)}, {json.dumps(val)}],")
    return "\n".join([
        f"import {{ {task['fn']} }} from \"./solution\";", "",
        "declare const process: { exit(code: number): never };", "",
        "function canon(v: unknown): string {",
        "  if (Array.isArray(v)) return \"[\" + v.map(canon).join(\",\") + \"]\";",
        "  if (v !== null && typeof v === \"object\") {",
        "    const o = v as Record<string, unknown>;",
        "    return \"{\" + Object.keys(o).sort().map((k) => JSON.stringify(k) + \":\" + canon(o[k])).join(\",\") + \"}\";",
        "  }",
        "  return JSON.stringify(v);",
        "}", "",
        "const cases: [string, () => unknown, string, unknown][] = [", *cases, "];",
        "let failed = 0;",
        "cases.forEach(([text, run, kind, want], i) => {",
        "  let got: unknown;",
        "  try {",
        "    got = run();",
        "  } catch (e) {",
        "    const msg = e instanceof Error ? e.message : String(e);",
        "    if (kind === \"err\" && msg === want) return;",
        "    failed++;",
        "    console.log(`FAIL case ${i + 1}: ${text} threw ${msg}; expected ` + (kind === \"err\" ? `the error ${JSON.stringify(want)}` : canon(want)));",
        "    return;",
        "  }",
        "  if (kind === \"err\" || canon(got) !== canon(want)) {",
        "    failed++;",
        "    console.log(`FAIL case ${i + 1}: ${text} returned ${canon(got)}; expected ` + (kind === \"err\" ? `the error ${JSON.stringify(want)}` : canon(want)));",
        "  }",
        "});",
        "console.log(`${cases.length - failed} passed, ${failed} failed`);",
        "process.exit(failed ? 1 : 0);", ""])


def run(cmd, cwd, timeout=120):
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                           env=dict(os.environ, PYTHONPATH=ROOT, NO_COLOR="1"))
        return p.returncode, (p.stdout + p.stderr).strip()
    except subprocess.TimeoutExpired:
        return -1, f"timeout after {timeout} s"


def evaluate(task, lang, code):
    """Runs the hidden tests on `code`: {"ok", "stage" ("compile" | "test" | "pass"), "feedback"}."""
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, f"solution.{EXT[lang]}"), "w", encoding="utf-8") as f:
            f.write(code)
        if lang == "klar":
            with open(os.path.join(d, "check.klar"), "w", encoding="utf-8") as f:
                f.write(tests_klar(task))
            code_, out = run([sys.executable, "-m", "klar", "test", "--json", "check.klar"], d)
            try:
                data = json.loads(out[out.index("{"):])
            except ValueError:
                # no report: a crash or a timeout of the tests, unless the program does not even type-check
                code2, text = run([sys.executable, "-m", "klar", "check", "check.klar"], d)
                stage = "compile" if code2 != 0 else "test"
                return {"ok": False, "stage": stage, "feedback": (text if code2 != 0 else out)[-3000:]}
            if data.get("stage") == "check":
                code2, text = run([sys.executable, "-m", "klar", "check", "check.klar"], d)
                return {"ok": False, "stage": "compile", "feedback": text[-3000:]}
            if data.get("ok"):
                return {"ok": True, "stage": "pass", "feedback": ""}
            failed = [t for t in data.get("tests", []) if t.get("status") != "passed"]
            _, text = run([sys.executable, "-m", "klar", "test", "check.klar"], d)
            return {"ok": False, "stage": "test", "feedback": text[-3000:], "failed": len(failed)}
        if lang == "python":
            with open(os.path.join(d, "check.py"), "w", encoding="utf-8") as f:
                f.write(tests_python(task))
            code_, out = run([sys.executable, "check.py"], d)
            if code_ == 0:
                return {"ok": True, "stage": "pass", "feedback": ""}
            stage = "compile" if "SyntaxError" in out or "IndentationError" in out else "test"
            return {"ok": False, "stage": stage, "feedback": out[-3000:]}
        with open(os.path.join(d, "check.ts"), "w", encoding="utf-8") as f:
            f.write(tests_typescript(task))
        tsc = shutil.which("tsc")
        if tsc is None:
            raise SystemExit("TypeScript needs `tsc` (npm install -g typescript)")
        code_, out = run([tsc, "--strict", "--target", "es2020", "--module", "commonjs",
                          "--outDir", "out", "check.ts", "solution.ts"], d)
        if code_ != 0:
            return {"ok": False, "stage": "compile", "feedback": out[-3000:]}
        code_, out = run(["node", os.path.join("out", "check.js")], d)
        if code_ == 0:
            return {"ok": True, "stage": "pass", "feedback": ""}
        return {"ok": False, "stage": "test", "feedback": out[-3000:]}


# ---- models -------------------------------------------------------------------------------------------------------------
def post(url, headers, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"content-type": "application/json",
                                                                               **headers})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as ex:
            if ex.code in (429, 500, 502, 503, 529) and attempt < 4:
                time.sleep(10 * (attempt + 1))
                continue
            raise SystemExit(f"API error {ex.code}: {ex.read().decode(errors='replace')[:500]}")


def anthropic(model, messages):
    key = os.environ.get("ANTHROPIC_API_KEY") or sys.exit("set ANTHROPIC_API_KEY")
    base = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/")
    r = post(base + "/v1/messages", {"x-api-key": key, "anthropic-version": "2023-06-01"},
             {"model": model, "max_tokens": 8000, "messages": messages})
    text = "".join(b.get("text", "") for b in r.get("content", []))
    u = r.get("usage", {})
    return text, u.get("input_tokens", 0), u.get("output_tokens", 0)


def openai(model, messages):
    key = os.environ.get("OPENAI_API_KEY") or sys.exit("set OPENAI_API_KEY")
    base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    r = post(base + "/chat/completions", {"authorization": f"Bearer {key}"}, {"model": model, "messages": messages})
    u = r.get("usage", {})
    return r["choices"][0]["message"]["content"], u.get("prompt_tokens", 0), u.get("completion_tokens", 0)


def reference(task, lang, refs=REFS):
    path = os.path.join(refs, lang, f"{task['id']}.{EXT[lang]}")
    if not os.path.exists(path):
        return "(no reference solution)", 0, 0
    with open(path, encoding="utf-8") as f:
        return "```\n" + f.read() + "```", 0, 0


def stub(task, lang):
    """A solution that only has the signature: the tests must type-check against it (`--validate`)."""
    if lang == "klar":
        return signature(task, lang) + " {\n  todo(\"stub\")\n}\n"
    if lang == "python":
        return signature(task, lang) + "\n    raise NotImplementedError\n"
    return signature(task, lang) + " {\n  throw new Error(\"stub\");\n}\n"


def validate(tasks, langs):
    """Every test file type-checks against a stub in every language: the suite is expressible everywhere."""
    bad = 0
    for task in tasks:
        for lang in langs:
            with tempfile.TemporaryDirectory() as d:
                with open(os.path.join(d, f"solution.{EXT[lang]}"), "w", encoding="utf-8") as f:
                    f.write(stub(task, lang))
                if lang == "klar":
                    with open(os.path.join(d, "check.klar"), "w", encoding="utf-8") as f:
                        f.write(tests_klar(task))
                    code, out = run([sys.executable, "-m", "klar", "check", "check.klar"], d)
                elif lang == "python":
                    with open(os.path.join(d, "check.py"), "w", encoding="utf-8") as f:
                        f.write(tests_python(task))
                    code, out = run([sys.executable, "-m", "py_compile", "check.py"], d)
                else:
                    with open(os.path.join(d, "check.ts"), "w", encoding="utf-8") as f:
                        f.write(tests_typescript(task))
                    code, out = run([shutil.which("tsc") or "tsc", "--strict", "--noEmit", "--target", "es2020",
                                     "--module", "commonjs", "check.ts", "solution.ts"], d)
                if code != 0:
                    bad += 1
                    print(f"BAD {task['id']} {lang}: {out[:600]}")
    print(f"validate: {len(tasks) * len(langs) - bad}/{len(tasks) * len(langs)} test files type-check")
    return 1 if bad else 0


# ---- the benchmark ------------------------------------------------------------------------------------------------------
def solve(task, lang, ask, attempts, spec, saved):
    """Up to `attempts` tries; returns the record of this (task, language)."""
    messages = [{"role": "user", "content": prompt(task, lang, spec)}]
    rec = {"task": task["id"], "lang": lang, "attempts": [], "solved": False, "tokens_in": 0, "tokens_out": 0}
    for k in range(attempts):
        key = f"{task['id']}/{lang}/{k}"
        if saved is not None:
            if key not in saved:
                break
            text, tin, tout = saved[key]["text"], saved[key]["in"], saved[key]["out"]
        else:
            text, tin, tout = ask(task, lang, messages)
        rec["answers"] = rec.get("answers", {})
        rec["answers"][key] = {"text": text, "in": tin, "out": tout}
        rec["tokens_in"] += tin
        rec["tokens_out"] += tout
        result = evaluate(task, lang, extract_code(text))
        rec["attempts"].append({"stage": result["stage"], "feedback": result["feedback"][:1500]})
        if result["ok"]:
            rec["solved"] = True
            break
        messages += [{"role": "assistant", "content": text},
                     {"role": "user", "content": "That did not work. "
                      + ("The compiler said:" if result["stage"] == "compile" else "The tests said:")
                      + f"\n\n{result['feedback']}\n\nReply with the corrected complete file in one code block."}]
    return rec


def summary(records, langs):
    rows = []
    for lang in langs:
        rs = [r for r in records if r["lang"] == lang]
        if not rs:
            continue
        n = len(rs)
        first = sum(1 for r in rs if r["solved"] and len(r["attempts"]) == 1)
        solved = sum(1 for r in rs if r["solved"])
        tries = [a for r in rs for a in r["attempts"]]
        failed_tries = [a for a in tries if a["stage"] != "pass"]
        rows.append({"lang": lang, "tasks": n, "first_try": first, "solved": solved,
                     "attempts": len(tries), "compile_failures": sum(1 for a in failed_tries if a["stage"] == "compile"),
                     "test_failures": sum(1 for a in failed_tries if a["stage"] == "test"),
                     "tokens": sum(r["tokens_in"] + r["tokens_out"] for r in rs)})
    return rows


def markdown(rows, title):
    out = [f"# {title}", "", "| language | solved first try | solved | attempts | failures caught by the compiler | "
           "failures found only by tests | tokens |", "|---|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        caught = r["compile_failures"] + r["test_failures"]
        share = f" ({100 * r['compile_failures'] // caught}%)" if caught else ""
        out.append(f"| {NAMES[r['lang']]} | {r['first_try']}/{r['tasks']} | {r['solved']}/{r['tasks']} | "
                   f"{r['attempts']} | {r['compile_failures']}{share} | {r['test_failures']} | {r['tokens']:,} |")
    return "\n".join(out) + "\n"


def klar_spec():
    p = subprocess.run([sys.executable, "-m", "klar", "spec"], capture_output=True, text=True, cwd=ROOT,
                       env=dict(os.environ, PYTHONPATH=ROOT))
    return p.stdout


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--provider", choices=["anthropic", "openai", "reference", "replay"], default="anthropic")
    ap.add_argument("--model", default="claude-sonnet-4-5")
    ap.add_argument("-l", "--lang", nargs="+", choices=LANGS, default=list(LANGS))
    ap.add_argument("-k", "--filter", help="only tasks whose id contains this text")
    ap.add_argument("--attempts", type=int, default=3)
    ap.add_argument("--replay", help="a results directory to re-score (with --provider replay)")
    ap.add_argument("--name", help="results/<name> (default: provider-model)")
    ap.add_argument("--suite", choices=sorted(SUITES), default="own",
                    help="own: tasks/tasks.json; humaneval, mbpp: from MultiPL-E (bench/ai/build_suites.py)")
    ap.add_argument("--validate", action="store_true",
                    help="no model: check that every test file type-checks against a stub in every language")
    args = ap.parse_args(argv)
    tasks_path, refs = SUITES[args.suite]
    with open(tasks_path, encoding="utf-8") as f:
        tasks = [t for t in json.load(f) if not args.filter or args.filter in t["id"]]
    if args.validate:
        return validate(tasks, args.lang)
    saved = None
    if args.provider == "replay":
        with open(os.path.join(args.replay, "answers.json"), encoding="utf-8") as f:
            saved = json.load(f)
    if args.provider == "anthropic":
        def ask(task, lang, messages):
            return anthropic(args.model, messages)
    elif args.provider == "openai":
        def ask(task, lang, messages):
            return openai(args.model, messages)
    else:
        def ask(task, lang, messages):
            return reference(task, lang, refs)
    spec = klar_spec() if "klar" in args.lang else ""
    records = []
    for task in tasks:
        for lang in args.lang:
            rec = solve(task, lang, ask, args.attempts, spec, saved)
            records.append(rec)
            mark = "ok " if rec["solved"] else "FAIL"
            print(f"{mark} {task['id']:<16} {lang:<10} attempts {len(rec['attempts'])} "
                  f"({', '.join(a['stage'] for a in rec['attempts'])})", flush=True)
    rows = summary(records, args.lang)
    name = args.name or (args.provider if args.provider in ("reference", "replay") else
                         f"{args.provider}-{args.model}")
    if args.suite != "own":
        name = f"{args.suite}-{name}"
    title = f"LLM benchmark: {name} ({len(tasks)} tasks, up to {args.attempts} attempts)"
    print("\n" + markdown(rows, title))
    out_dir = os.path.join(HERE, "results", re.sub(r"[^A-Za-z0-9._-]", "_", name))
    os.makedirs(out_dir, exist_ok=True)
    answers = {k: v for r in records for k, v in r.pop("answers", {}).items()}
    with open(os.path.join(out_dir, "answers.json"), "w", encoding="utf-8") as f:
        json.dump(answers, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "report.json"), "w", encoding="utf-8") as f:
        json.dump({"summary": rows, "records": records}, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write(markdown(rows, title))
    return 0 if all(r["solved"] == r["tasks"] for r in rows) or args.provider not in ("reference",) else 1


if __name__ == "__main__":
    sys.exit(main())
