#!/usr/bin/env python3
"""Builds the outside task suites of the LLM benchmark (ROADMAP item 19): HumanEval and MBPP as MultiPL-E ships them,
turned into the task format of llm_bench.py, so Klar, Python and TypeScript get the same hidden tests.

    git clone https://github.com/nuprl/MultiPL-E /tmp/MultiPL-E
    python bench/ai/build_suites.py /tmp/MultiPL-E

Python is used here on purpose: the input is Python source (signatures with type hints and `assert candidate(...) ==
...` tests), read with the `ast` module. The method follows MultiPL-E (Cassano et al., 2022): a problem is kept when
its signature has a type every language can express and at least one test is a plain equality on literal values;
every kept test is checked against the canonical Python solution, so a case the reference does not pass is a fault of
the extraction and is dropped (the report counts them). Writes bench/ai/suites/<suite>/tasks.json, the Python
references in ref/python/ and report.md with what was dropped and why.

The MultiPL-E data is under a BSD-3-Clause licence with a machine-learning restriction (clause 4: not to be used as
training data); suites/LICENSE-MultiPL-E carries it, and the suites must stay out of any corpus for models (ROADMAP 17).
"""
import ast
import copy
import json
import math
import os
import shutil
import signal
import subprocess
import sys
import textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "suites")
INT_MAX = 2 ** 53 - 1      # the largest integer JavaScript holds exactly: larger ones would fail TypeScript unfairly


class Skip(Exception):
    pass


# parameter names that are keywords in one of the languages: renamed in every language alike (HumanEval/111 calls
# its parameter `test`, a Klar keyword); the keywords of Klar are klar/lexer.py KEYWORDS
RESERVED = {"and", "assert", "break", "const", "continue", "else", "ensures", "enum", "false", "fn", "for", "if",
            "impl", "in", "let", "match", "module", "not", "or", "property", "pub", "requires", "return", "test",
            "trait", "true", "type", "use", "uses", "var", "while", "with",
            # TypeScript
            "case", "catch", "class", "debugger", "default", "delete", "do", "export", "extends", "finally",
            "function", "import", "instanceof", "new", "null", "super", "switch", "this", "throw", "try", "typeof",
            "void", "yield", "let", "static", "implements", "interface", "package", "private", "protected", "public",
            "await", "arguments", "eval"}


def param_name(name):
    return name + "_value" if name in RESERVED else name


# ---- types: Python annotation -> the Klar-style type of llm_bench.py ------------------------------------------------
def klar_type(t):
    if t is None:
        raise Skip("an argument without a type")
    if isinstance(t, ast.Constant) and t.value is None:
        raise Skip("returns None")
    if isinstance(t, ast.Name):
        simple = {"int": "Int", "float": "Float", "bool": "Bool", "str": "Str"}
        if t.id in simple:
            return simple[t.id]
        raise Skip(f"type {t.id}")
    if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name):
        head = t.value.id
        args = t.slice.elts if isinstance(t.slice, ast.Tuple) else [t.slice]
        if head in ("List", "list") and len(args) == 1:
            return f"List[{klar_type(args[0])}]"
        if head in ("Optional",) and len(args) == 1:
            return f"Option[{klar_type(args[0])}]"
        if head in ("Dict", "dict") and len(args) == 2:
            k = klar_type(args[0])
            if k != "Str":
                raise Skip("a map with non-string keys")
            return f"Map[Str, {klar_type(args[1])}]"
        if head in ("Tuple", "tuple"):
            if len(args) == 2:
                return f"Pair[{klar_type(args[0])}, {klar_type(args[1])}]"
            raise Skip(f"a tuple of {len(args)}")
        raise Skip(f"type {head}")
    raise Skip(f"annotation {ast.dump(t)[:40]}")


def split_type(t):
    if "[" not in t:
        return t, []
    head, inner = t[:t.index("[")], t[t.index("[") + 1:-1]
    parts, depth, cur = [], 0, ""
    for c in inner:
        if c == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
            continue
        depth += c == "["
        depth -= c == "]"
        cur += c
    parts.append(cur.strip())
    return head, parts


def to_json(v, t, lenient=False):
    """The value as JSON for type `t`, or Skip when it does not fit (bools for ints, huge ints, NaN, ...). `lenient`
    (for what the Python reference returns): an integral float is an Int, as `2.0 == 2` in Python."""
    head, args = split_type(t)
    if head == "Int" and lenient and isinstance(v, float) and v.is_integer():
        v = int(v)
    if head == "Int":
        if isinstance(v, bool) or not isinstance(v, int) or abs(v) > INT_MAX:
            raise Skip("not an Int, or one above 2^53 (TypeScript cannot hold it exactly)")
        return v
    if head == "Float":
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise Skip("a value that is not a finite Float")
        return float(v)
    if head == "Bool":
        if not isinstance(v, bool):
            raise Skip("a value that is not a Bool")
        return v
    if head == "Str":
        if not isinstance(v, str):
            raise Skip("a value that is not a Str")
        return v
    if head == "List":
        if not isinstance(v, (list, tuple)):
            raise Skip("a value that is not a List")
        return [to_json(x, args[0], lenient) for x in v]
    if head == "Pair":
        if not isinstance(v, (list, tuple)) or len(v) != 2:
            raise Skip("a value that is not a pair")
        return [to_json(v[0], args[0], lenient), to_json(v[1], args[1], lenient)]
    if head == "Map":
        if not isinstance(v, dict) or not all(isinstance(k, str) for k in v):
            raise Skip("a value that is not a Map[Str, _]")
        return {k: to_json(x, args[1], lenient) for k, x in v.items()}
    if head == "Option":
        return None if v is None else to_json(v, args[0], lenient)
    raise Skip(f"type {t}")


def to_python(v, t):
    """A JSON value of type `t` as the Python test passes it: a Pair is a tuple, a Float a float."""
    head, args = split_type(t)
    if head == "List":
        return [to_python(x, args[0]) for x in v]
    if head == "Pair":
        return (to_python(v[0], args[0]), to_python(v[1], args[1]))
    if head == "Map":
        return {k: to_python(x, args[1]) for k, x in v.items()}
    if head == "Option":
        return None if v is None else to_python(v, args[0])
    if head == "Float":
        return float(v)
    return v


ADAPTER = """

# adapted by bench/ai/build_suites.py: the canonical solution returns tuples where the typed signature says list
# (or lists where it says a pair); the results are converted, the solution itself is unchanged
def _conform(v, t):
    if t.startswith("List["):
        return [_conform(x, t[5:-1]) for x in v]
    if t.startswith("Pair["):
        inner, depth, cut = t[5:-1], 0, 0
        for i, c in enumerate(inner):
            depth += c == "["
            depth -= c == "]"
            if c == "," and depth == 0:
                cut = i
                break
        return (_conform(v[0], inner[:cut].strip()), _conform(v[1], inner[cut + 1:].strip()))
    if t.startswith("Option["):
        return None if v is None else _conform(v, t[7:-1])
    if t.startswith("Map["):
        return {k: _conform(x, t[4:-1].split(",", 1)[1].strip()) for k, x in v.items()}
    return v


_canonical_{name} = {name}


def {name}(*args):
    return _conform(_canonical_{name}(*args), {ret!r})
"""


# ---- one problem ------------------------------------------------------------------------------------------------------
def entry_point(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "test_check":
            for c in ast.walk(node):
                if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == "check" and c.args:
                    return c.args[0].id
    raise Skip("no entry point")


def literal_cases(tree):
    """(args, expected) of every `assert candidate(<literals>) == <literal>` in check(); the count of other asserts."""
    cases, other = [], 0
    check = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "check"), None)
    if check is None:
        raise Skip("no check()")
    for node in ast.walk(check):
        if not isinstance(node, ast.Assert):
            continue
        t = node.test
        ok = False
        if isinstance(t, ast.Compare) and len(t.ops) == 1 and isinstance(t.ops[0], ast.Eq):
            left, right = t.left, t.comparators[0]
            if isinstance(right, ast.Call) and not isinstance(left, ast.Call):
                left, right = right, left
            if isinstance(left, ast.Call) and isinstance(left.func, ast.Name) and left.func.id == "candidate" \
                    and not left.keywords:
                try:
                    args = [ast.literal_eval(a) for a in left.args]
                    want = ast.literal_eval(right)
                    cases.append((args, want))
                    ok = True
                except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
                    pass
        if not ok:
            other += 1
    return cases, other


class Timeout(Exception):
    pass


def _alarm(signum, frame):
    raise Timeout()


def same(a, b):
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    if isinstance(a, bool) != isinstance(b, bool):
        return False
    return a == b


def run_reference(src, fn, args):
    env = {"__name__": "reference"}
    exec(compile(src, "<reference>", "exec"), env)  # noqa: S102 - the canonical solutions of the dataset
    if hasattr(signal, "SIGALRM"):
        signal.signal(signal.SIGALRM, _alarm)
        signal.alarm(60)                   # generous: the build must not depend on how busy the machine is
    try:
        return env[fn](*copy.deepcopy(args))
    finally:
        if hasattr(signal, "SIGALRM"):
            signal.alarm(0)


def docstring_of(fn_node):
    doc = ast.get_docstring(fn_node, clean=True) or ""
    return textwrap.dedent(doc).strip()


PLUS_CASES = 60      # tests of a HumanEval+ problem: the base tests and evenly spaced EvalPlus inputs, at most this


def build_problem(pid, text, reference, plus=None):
    """The task (llm_bench.py format) and its Python reference, or Skip with the reason. `plus` (HumanEval+): the
    EvalPlus record of the problem — its inputs become more tests, with the results of its canonical solution."""
    tree = ast.parse(text)
    name = entry_point(tree)
    fn = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name), None)
    if fn is None:
        raise Skip("the entry point is not a top-level function")
    if fn.args.vararg or fn.args.kwarg or fn.args.kwonlyargs or fn.args.defaults:
        raise Skip("default, keyword or variadic parameters")
    params = [[param_name(a.arg), klar_type(a.annotation)] for a in fn.args.args]
    ret = klar_type(fn.returns)
    cases, other = literal_cases(tree)
    tests, dropped, failing, adapt = [], {"not a literal equality": other}, 0, False
    for args, want in cases:
        try:
            if len(args) != len(params):
                raise Skip("a wrong number of arguments")
            jargs = [to_json(a, t) for a, (_, t) in zip(args, params)]
            jwant = to_json(want, ret)
        except Skip as ex:
            dropped[str(ex)] = dropped.get(str(ex), 0) + 1
            continue
        # the reference gets the arguments as the typed test passes them (a Float is a float, a pair a tuple)
        try:
            got = run_reference(reference, name, [to_python(a, t) for a, (_, t) in zip(jargs, params)])
            agrees = same(to_json(got, ret, lenient=True), jwant)
            if agrees and got != to_python(jwant, ret):
                adapt = True               # equal up to tuple / list: the harness compares exactly
        except Exception:  # noqa: BLE001 - any failure of the reference counts against the problem
            agrees = False
        if not agrees:
            failing += 1
            continue
        tests.append([jargs, jwant])
    if failing:
        # MultiPL-E's typed version contradicts the problem (HumanEval/92: ints typed as float, checked with
        # isinstance int); the whole problem goes, not just the cases
        raise Skip("the canonical solution fails some of its typed tests")
    if not tests:
        raise Skip("no test is a literal equality the reference passes")
    if plus is not None:
        tests, reference = plus_tests(name, params, ret, tests, plus, dropped)
        adapt = False
    if adapt:
        reference = reference.rstrip() + "\n" + ADAPTER.replace("{name}", name).replace("{ret!r}", repr(ret))
    statement = docstring_of(fn)
    if not statement:
        raise Skip("no statement")
    task = {"id": pid, "fn": name, "params": params, "ret": ret, "statement": statement, "tests": tests}
    return task, {k: v for k, v in dropped.items() if v}, reference


def plus_tests(name, params, ret, tests, plus, dropped):
    """The base tests and EvalPlus's extra inputs with the results of its canonical solution (as EvalPlus computes
    them). Float results are compared exactly here, so problems that return a Float keep the base tests only."""
    reference = plus["prompt"] + plus["canonical_solution"]
    if "Float" in ret:
        dropped["Float result: no extra inputs"] = dropped.get("Float result: no extra inputs", 0) + 1
        return tests, reference
    inputs = plus.get("plus_input") or []
    room = max(0, PLUS_CASES - len(tests))
    step = max(1, len(inputs) // room) if room else len(inputs) + 1
    seen = {json.dumps(t[0], sort_keys=True) for t in tests}
    out = list(tests)
    for args in inputs[::step]:
        if len(out) >= PLUS_CASES:
            break
        try:
            if len(args) != len(params):
                raise Skip("a wrong number of arguments")
            jargs = [to_json(a, t) for a, (_, t) in zip(args, params)]
            key = json.dumps(jargs, sort_keys=True)
            if key in seen:
                continue
            got = run_reference(reference, name, [to_python(a, t) for a, (_, t) in zip(jargs, params)])
            jwant = to_json(got, ret, lenient=True)
            if len(json.dumps([jargs, jwant])) > 2000:
                raise Skip("larger than 2000 characters as a test")
        except Skip as ex:
            dropped[f"extra input: {ex}"] = dropped.get(f"extra input: {ex}", 0) + 1
            continue
        except Exception:  # noqa: BLE001 - an input the canonical solution cannot take
            dropped["extra input the canonical solution fails on"] = \
                dropped.get("extra input the canonical solution fails on", 0) + 1
            continue
        seen.add(key)
        out.append([jargs, jwant])
    if any(to_python(w, ret) != run_reference(reference, name, [to_python(a, t) for a, (_, t) in zip(j, params)])
           for j, w in out):
        reference = reference.rstrip() + "\n" + ADAPTER.replace("{name}", name).replace("{ret!r}", repr(ret))
    return out, reference


def humaneval_plus(src_dir):
    """HumanEval+ (EvalPlus, shipped with MultiPL-E): the typed signatures of MultiPL-E, many more tests."""
    plus = {}
    with open(os.path.join(src_dir, "datasets", "HumanEvalPlus-v0.1.8.jsonl"), encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            plus[r["task_id"].split("/")[1]] = r
    for pid, text, reference in humaneval(src_dir):
        num = pid.split("_")[1]
        if num in plus:
            yield "hep_" + pid[3:], text, reference, plus[num]


def humaneval(src_dir):
    d = os.path.join(src_dir, "datasets", "originals")
    for f in sorted(os.listdir(d), key=lambda n: int(n.split("_")[1])):
        if not f.endswith(".py"):
            continue
        with open(os.path.join(d, f), encoding="utf-8") as fh:
            text = fh.read()
        pid = "he_" + f[len("HumanEval_"):-3]
        reference = text.split("### Unit tests below ###")[0]
        yield pid, text, reference


def mbpp(src_dir):
    d = os.path.join(src_dir, "datasets", "mbpp-typed")
    with open(os.path.join(src_dir, "datasets", "sanitized-mbpp.json"), encoding="utf-8") as fh:
        refs = {str(x["task_id"]): x["code"] for x in json.load(fh)}
    for f in sorted(os.listdir(d), key=lambda n: int(n.split("_")[1])):
        if not f.endswith(".py"):
            continue
        with open(os.path.join(d, f), encoding="utf-8") as fh:
            text = fh.read()
        num = f.split("_")[1]
        if num not in refs:
            continue
        yield "mbpp_" + f[len("mbpp_"):-3], text, refs[num]


def write_suite(name, problems, src_dir, commit):
    out_dir = os.path.join(OUT, name)
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(os.path.join(out_dir, "ref", "python"))
    tasks, skipped, dropped_cases, kept_cases = [], {}, {}, 0
    total = 0
    for pid, text, reference, *extra in problems:
        total += 1
        try:
            task, dropped, reference = build_problem(pid, text, reference, *extra)
        except Skip as ex:
            skipped[str(ex)] = skipped.get(str(ex), 0) + 1
            continue
        except SyntaxError:
            skipped["unreadable Python"] = skipped.get("unreadable Python", 0) + 1
            continue
        tasks.append(task)
        kept_cases += len(task["tests"])
        for k, v in dropped.items():
            dropped_cases[k] = dropped_cases.get(k, 0) + v
        with open(os.path.join(out_dir, "ref", "python", pid + ".py"), "w", encoding="utf-8") as fh:
            fh.write(reference.rstrip() + "\n")
    with open(os.path.join(out_dir, "tasks.json"), "w", encoding="utf-8") as fh:
        json.dump(tasks, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    adapted = sum(1 for t in tasks if "_canonical_" in open(os.path.join(out_dir, "ref", "python", t["id"] + ".py"),
                                                              encoding="utf-8").read())
    lines = [f"# {name}: {len(tasks)} of {total} problems", "",
             f"Built by `bench/ai/build_suites.py` from MultiPL-E at commit `{commit}`.", "",
             f"Kept: {len(tasks)} problems, {kept_cases} test cases (each passed by the canonical Python solution, "
             f"called with the typed arguments). In {adapted} references the results are converted to the declared "
             "type (tuples where the signature says list); the solutions themselves are unchanged.", "",
             "| skipped problems: reason | count |", "|---|---:|"]
    lines += [f"| {k} | {v} |" for k, v in sorted(skipped.items(), key=lambda kv: -kv[1])]
    lines += ["", "| dropped test cases of kept problems: reason | count |", "|---|---:|"]
    lines += [f"| {k} | {v} |" for k, v in sorted(dropped_cases.items(), key=lambda kv: -kv[1])]
    with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"{name}: {len(tasks)}/{total} problems, {kept_cases} cases; skipped {sum(skipped.values())}")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        raise SystemExit(__doc__)
    src = argv[0]
    try:
        commit = subprocess.run(["git", "-C", src, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    except OSError:
        commit = "?"
    os.makedirs(OUT, exist_ok=True)
    shutil.copy(os.path.join(src, "LICENSE"), os.path.join(OUT, "LICENSE-MultiPL-E"))
    write_suite("humaneval", humaneval(src), src, commit or "?")
    write_suite("mbpp", mbpp(src), src, commit or "?")
    write_suite("humaneval_plus", humaneval_plus(src), src, commit or "?")
    return 0


if __name__ == "__main__":
    sys.exit(main())
