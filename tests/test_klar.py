"""Compiler test-suite. Run: python -m unittest discover -s tests"""
import io
import json
import os
import re
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from klar.builtins import GLOBALS, METHODS  # noqa: E402
from klar.cli import main as cli_main  # noqa: E402
from klar.codegen import CompiledProgram, Unsupported  # noqa: E402
from klar.errors import KlarRuntimeError  # noqa: E402
from klar.interpreter import Interpreter, Profiler, run_with_big_stack  # noqa: E402
from klar.loader import load_path, load_source  # noqa: E402


def diags(src):
    return [d for d in load_source(src, "t.klar").diags if d.span.file != "prelude.klar"]


def codes(src):
    return [d.code for d in diags(src)]


def errors(src):
    return [d.code for d in diags(src) if d.severity == "error"]


def _run_backend(loaded, compiled, stdin, args):
    out = io.StringIO()
    if compiled:
        runner = CompiledProgram(loaded, out=out, inp=io.StringIO(stdin), err_stream=io.StringIO(), cli_args=args)
    else:
        runner = Interpreter(loaded, out=out, inp=io.StringIO(stdin), err_stream=io.StringIO(), cli_args=args)
    try:
        run_with_big_stack(runner.run_main)
    except KlarRuntimeError as ex:
        return out.getvalue(), ex
    return out.getvalue(), None


def run(src, stdin="", args=(), root=None):
    """Runs with BOTH backends; their stdout and runtime error codes must agree (differential testing)."""
    loaded = load_source(src, "t.klar", root=root)
    errs = [d for d in loaded.diags if d.severity == "error"]
    if errs:
        raise AssertionError("\n".join(d.format(loaded.sources.get(d.span.file)) for d in errs))
    out_i, err_i = _run_backend(loaded, False, stdin, args)
    try:
        out_c, err_c = _run_backend(loaded, True, stdin, args)
    except Unsupported:
        out_c, err_c = out_i, err_i
    assert out_i == out_c, f"backends disagree on output:\ninterpreter: {out_i!r}\ncompiled:    {out_c!r}"
    assert (err_i and err_i.code) == (err_c and err_c.code), \
        f"backends disagree on error: {err_i and err_i.code} vs {err_c and err_c.code}"
    if err_i is not None:
        raise err_i
    return out_i


def runtime_code(src, stdin=""):
    try:
        run(src, stdin=stdin)
    except KlarRuntimeError as ex:
        return ex.code
    return None


def cli(*argv):
    old = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = io.StringIO(), io.StringIO()
    try:
        code = cli_main(list(argv))
        return code, sys.stdout.getvalue(), sys.stderr.getvalue()
    finally:
        sys.stdout, sys.stderr = old


KLAR_TEST_FILES = [
    os.path.join(ROOT, "examples", f) for f in ("hello.klar", "bank.klar", "collections.klar", "shapes.klar",
                                                  "features.klar")
] + [os.path.join(ROOT, "klar", "std", f) for f in sorted(os.listdir(os.path.join(ROOT, "klar", "std")))
     if f.endswith(".klar")] + [os.path.join(ROOT, "tests", "stdlib", "builtins_test.klar")]


class KlarTestFiles(unittest.TestCase):
    """Every example, std module and the built-in test file must pass `klar test` (incl. properties)."""

    def test_all_klar_tests_pass(self):
        for path in KLAR_TEST_FILES:
            with self.subTest(path=os.path.relpath(path, ROOT)):
                code, out, err = cli("test", "-q", path)
                self.assertEqual(code, 0, out + err)

    def test_examples_run(self):
        for name in ("hello", "bank", "collections", "shapes", "features"):
            with self.subTest(example=name):
                code, out, err = cli("run", "-q", os.path.join(ROOT, "examples", f"{name}.klar"))
                self.assertEqual(code, 0, out + err)

    def test_every_builtin_is_tested(self):
        with open(os.path.join(ROOT, "tests", "stdlib", "builtins_test.klar"), encoding="utf-8") as f:
            klar_tests = f.read()
        with open(os.path.abspath(__file__), encoding="utf-8") as f:
            py_tests = f.read()
        untested = []
        for owner, ms in METHODS.items():
            for name in ms:
                if not re.search(r"\." + name + r"\(", klar_tests):
                    untested.append(f"{owner}.{name}")
        for name in GLOBALS:
            if not re.search(r"\b" + name + r"\(", klar_tests + py_tests):
                untested.append(name)
        self.assertEqual(untested, [], "built-ins without tests")


class Backends(unittest.TestCase):
    """The compiled backend must behave exactly like the interpreter on every program we have."""

    def programs(self):
        out = [os.path.join(ROOT, "examples", f) for f in ("hello.klar", "bank.klar", "collections.klar",
                                                             "shapes.klar", "features.klar")]
        bench = os.path.join(ROOT, "bench", "programs")
        out += [os.path.join(bench, b, b + ".klar") for b in sorted(os.listdir(bench))]
        return out

    def test_examples_and_benchmarks_agree(self):
        for path in self.programs():
            with self.subTest(program=os.path.relpath(path, ROOT)):
                loaded = load_path(path)
                self.assertFalse(loaded.has_errors())
                CompiledProgram(loaded)  # must not be Unsupported
                strip = lambda s: "\n".join(l for l in s.splitlines() if not l.startswith("time_ms="))
                out_i, err_i = _run_backend(loaded, False, "", ())
                out_c, err_c = _run_backend(loaded, True, "", ())
                self.assertEqual(strip(out_i), strip(out_c))
                self.assertEqual(err_i, err_c)

    def test_compiled_error_has_klar_stack(self):
        loaded = load_source("fn f(x: Int) -> Int\n  requires x > 0\n{ return x }\n"
                             "fn g() -> Int { return f(0) }\nfn main() uses io { print(g()) }", "t.klar")
        out, ex = _run_backend(loaded, True, "", ())
        self.assertEqual(ex.code, "R0002")
        self.assertEqual(ex.details, ["x = 0"])
        self.assertEqual([n for n, _ in ex.stack], ["main", "g", "f"])
        self.assertEqual(ex.stack[-1][1].line, 4)

    def test_closures_capture_per_iteration(self):
        out = run("""
fn main() uses io {
  var fns: List[fn() -> Int] = []
  for i in range(0, 3) {
    let k = i * 10
    fns = fns.push(fn() => k + i)
  }
  print(fns.map(fn(f) => f()))
}""")
        self.assertEqual(out, "[0, 11, 22]\n")

    def test_lambdas_cannot_capture_vars(self):
        assign = "fn main() uses io {\n var counter = 0\n let bump = fn(n: Int) {\n counter = counter + n\n }\n bump(5)\n}"
        self.assertEqual(errors(assign), ["E0216"])
        read = "fn main() uses io {\n var n = 1\n let f = fn(x: Int) => x + n\n n = 5\n print(f(1))\n}"
        self.assertEqual(errors(read), ["E0216"])
        snapshot = "fn main() uses io {\n var n = 1\n let n_now = n\n let f = fn(x: Int) => x + n_now\n n = 5\n print(f(1))\n}"
        self.assertEqual(errors(snapshot), [])


class Programs(unittest.TestCase):
    def test_generics(self):
        out = run("""
fn identity[T](x: T) -> T { return x }
fn same[T](a: T, b: T) -> Bool { return a == b }
fn main() uses io {
  print(identity(5))
  print(identity("s"))
  print(same([1], [1]))
}""")
        self.assertEqual(out, "5\ns\ntrue\n")

    def test_generic_types_and_aliases(self):
        out = run("""
type Box[T] { value: T }
type Ids = List[Int]
enum Tree[T] { Leaf, Node(left: Tree[T], value: T, right: Tree[T]) }
fn size[T](t: Tree[T]) -> Int {
  return match t { Tree.Leaf => 0, Tree.Node(l, _, r) => size(l) + 1 + size(r) }
}
fn unbox[T](b: Box[T]) -> T { return b.value }
fn main() uses io {
  let ids: Ids = [1, 2]
  let t = Tree.Node(left: Tree.Leaf, value: "x", right: Tree.Node(left: Tree.Leaf, value: "y", right: Tree.Leaf))
  print(size(t))
  print(unbox(Box { value: ids }).len())
  print(Box { value: 1 } with { value: 2 })
}""")
        self.assertEqual(out, "2\n2\nBox { value: 2 }\n")

    def test_generic_field_type_is_checked(self):
        self.assertIn("E0202", errors("type Box[T] { value: T }\nfn f(b: Box[Int]) -> Str { return b.value }"))
        self.assertIn("E0105", errors("type Box[T] { value: T }\nfn f(b: Box) { }"))

    def test_constants(self):
        out = run("""
const BASE: Int = 10
const LIMIT: Int = BASE * 3
fn main() uses io { print(LIMIT + 1) }""")
        self.assertEqual(out, "31\n")
        self.assertIn("E0604", errors("const A: Int = B\nconst B: Int = 1"))
        self.assertIn("E0103", errors("const limit: Int = 1"))
        self.assertIn("E0207", errors("const A: Int = 1\nfn f() { A = 2 }"))
        self.assertIn("E0401", errors("const T: Int = now_ms()"))

    def test_match_guards(self):
        out = run("""
fn kind(n: Int) -> Str {
  return match n { 0 => "zero", x if x < 0 => "neg", _ => "pos" }
}
fn main() uses io { print([0, -1, 5].map(fn(n) => kind(n))) }""")
        self.assertEqual(out, '["zero", "neg", "pos"]\n')
        # a guarded arm never makes a match exhaustive
        self.assertIn("E0301", errors("fn f(b: Bool) -> Int { return match b { true => 1, false if 1 > 0 => 2 } }"))

    def test_match_with_returning_arm(self):
        out = run("""
fn half(n: Int) -> Result[Int, Str] {
  return match n % 2 == 0 { true => Ok(n / 2), false => Err("odd") }
}
fn quarter(n: Int) -> Result[Int, Str] {
  let h = match half(n) {
    Ok(x) => x,
    Err(e) => { return Err(e) },
  }
  return half(h)
}
fn main() uses io {
  print(quarter(8))
  print(quarter(6))
}""")
        self.assertEqual(out, "Ok(2)\nErr(\"odd\")\n")

    def test_option_question_mark(self):
        out = run("""
fn first_even(xs: List[Int]) -> Option[Int] {
  let x = xs.find(fn(n) => n % 2 == 0)?
  return Some(x * 10)
}
fn main() uses io {
  print(first_even([1, 4]))
  print(first_even([1, 3]))
}""")
        self.assertEqual(out, "Some(40)\nNone\n")

    def test_loops_and_vars(self):
        out = run("""
fn main() uses io {
  var i = 0
  var acc: List[Int] = []
  while true {
    i = i + 1
    if i % 2 == 0 { continue }
    if i > 7 { break }
    acc = acc.push(i)
  }
  print(acc)
}""")
        self.assertEqual(out, "[1, 3, 5, 7]\n")

    def test_lambda_block_and_record_fn_field(self):
        out = run("""
type Handler { name: Str, run: fn(Int) -> Int }
fn main() uses io {
  let h = Handler { name: "double", run: fn(x: Int) -> Int {
    let y = x * 2
    return y
  } }
  print(h.run(21))
}""")
        self.assertEqual(out, "42\n")

    def test_map_and_interpolation(self):
        out = run("""
fn main() uses io {
  let m = Map { "a": 1, "b": 2 }
  let m2 = m.set("c", 3).remove("a")
  print("{m2} {m2.keys()} {m.len()} \\{literal\\}")
}""")
        self.assertEqual(out, 'Map { "b": 2, "c": 3 } ["b", "c"] 2 {literal}\n')

    def test_method_chain_on_new_lines(self):
        out = run("""
fn main() uses io {
  let s = [3, 1, 2]
    .sort()
    .map(fn(x) => x.to_str())
    .join("-")
  print(s)
}""")
        self.assertEqual(out, "1-2-3\n")

    def test_ufcs_and_named_args(self):
        out = run("""
type Acc { balance: Int }
fn add(a: Acc, amount: Int) -> Acc { return a with { balance: a.balance + amount } }
fn clamp3(x: Int, low: Int, high: Int) -> Int { return x.max(low).min(high) }
fn main() uses io {
  print(Acc { balance: 1 }.add(2).balance)
  print(clamp3(high: 10, x: 50, low: 0))
}""")
        self.assertEqual(out, "3\n10\n")

    def test_io_globals(self):
        out = run("""
fn main() uses io {
  match read_line() {
    Some(line) => print("got {line}"),
    None => print("eof"),
  }
  print(read_line())
  print(cli_args())
}""", stdin="hello\n", args=("a", "b"))
        self.assertEqual(out, 'got hello\nNone\n["a", "b"]\n')

    def test_time_and_random(self):
        out = run("""
fn main() uses io, time, rand {
  let t = now_ms()
  let a = now_ns()
  let b = now_ns()
  let r = random_int(1, 3)
  print(t > 0 and r >= 1 and r <= 3 and b >= a)
}""")
        self.assertEqual(out, "true\n")

    def test_files(self):
        for compiled in (False, True):
            with tempfile.TemporaryDirectory() as d:
                path = os.path.join(d, "f.txt").replace("\\", "/")
                loaded = load_source(f"""
fn main() uses io, fs {{
  print(file_exists("{path}"))
  let _ = write_file("{path}", "data")
  print(file_exists("{path}"))
  print(read_file("{path}"))
  print(read_file("{path}.missing").is_err())
}}""", "t.klar")
                out, ex = _run_backend(loaded, compiled, "", ())
                self.assertIsNone(ex)
                self.assertEqual(out, 'false\ntrue\nOk("data")\ntrue\n')
        self.assertIn("E0401", errors('fn f() -> Bool { return file_exists("x") }'))

    def test_dbg_and_todo(self):
        loaded = load_source("fn main() uses io { let x = dbg(2 + 3)\n print(x) }", "t.klar")
        out, err = io.StringIO(), io.StringIO()
        it = Interpreter(loaded, out=out, err_stream=err)
        run_with_big_stack(it.run_main)
        self.assertEqual(out.getvalue(), "5\n")
        self.assertIn("2 + 3 = 5", err.getvalue())
        self.assertIn("W0404", codes('fn f(x: Int) -> Int { todo("later") }'))
        self.assertEqual(runtime_code('fn main() { todo("x") }'), "R0012")

    def test_main_err_is_runtime_error(self):
        self.assertEqual(runtime_code("""
fn main() -> Result[Unit, Str] {
  let _n = "x".to_int().ok_or("not a number")?
  return Ok(())
}"""), "R0007")

    def test_runtime_errors(self):
        # values that are only known at run time (from input) still fail safely at run time
        self.assertEqual(runtime_code("fn main() uses io { let z = read_line().unwrap_or(\"0\").len().to_float() - 1.0\n"
                                      " print(1.0 / z) }", stdin="x"), "R0001")
        self.assertEqual(runtime_code("fn f(x: Int) -> Int\n requires x > 0\n{ return x }\n"
                                      "fn main() uses io { print(f(read_line().unwrap_or(\"\").len())) }"), "R0002")
        self.assertEqual(runtime_code('fn main() { fail("boom") }'), "R0004")
        self.assertEqual(runtime_code("fn f(n: Int) -> Int { if n > 100000 { return n }\n return f(n + 1) + 1 }\n"
                                      "fn main() uses io { print(f(0)) }"), "R0006")
        self.assertEqual(runtime_code("fn main() uses io { print([1].set(5, 2)) }"), "R0011")
        self.assertEqual(runtime_code("fn main() uses io { let x = 0.0 - read_line().unwrap_or(\"ab\").len().to_float()\n"
                                      " print(x.sqrt()) }"), "R0009")


class CompileTimeSafety(unittest.TestCase):
    """Failures that Klar rejects before the program runs (E07xx)."""

    def test_division_needs_proof(self):
        self.assertEqual(errors("fn f(a: Int, b: Int) -> Int { return a / b }"), ["E0701"])
        self.assertEqual(errors("fn f(a: Int) -> Int { return a % (2 - 2) }"), ["E0701"])
        ok = [
            "fn f(a: Int, b: Int) -> Int\n requires b != 0\n{ return a / b }",
            "fn f(a: Int, b: Int) -> Int { if b == 0 { return 0 }\n return a / b }",
            "fn f(a: Int, b: Int) -> Int { if b != 0 { return a / b }\n return 0 }",
            "fn f(a: Int, b: Int) -> Int { return match b { 0 => 0, _ => a / b } }",
            "fn f(xs: List[Int]) -> Int { if xs.is_empty() { return 0 }\n return xs.sum() / xs.len() }",
            "fn f(n: Int) -> Int { var d = 3\n var c = 0\n while d < n { c = c + n % d\n d = d + 2 }\n return c }",
            "fn f(n: Int) -> Int { var t = 0\n for i in range(1, n) { t = t + n / i }\n return t }",
            "fn f(a: Int, b: Int) -> Int { var x = a\n var y = b\n while y != 0 { let t = x % y\n x = y\n y = t }\n"
            " return x }",
            "fn f(a: Int, b: Int) -> Int { return a / (b.abs() + 1) }",
            "fn pos(x: Int) -> Int\n ensures result > 0\n{ return x.abs() + 1 }\nfn f(a: Int) -> Int { return a / pos(a) }",
            "fn f(a: Float, b: Float) -> Float { return a / b }",
        ]
        for src in ok:
            self.assertEqual(errors(src), [], src)

    def test_parameter_fix_suggests_requires(self):
        d = [x for x in diags("fn f(a: Int, b: Int) -> Int { return a / b }") if x.code == "E0701"][0]
        self.assertIn("requires b != 0", d.hint)
        self.assertFalse(d.fix["safe"])

    def test_float_division_by_literal_zero(self):
        self.assertEqual(errors("fn f(a: Float) -> Float { return a / 0.0 }"), ["E0701"])

    def test_unconditional_recursion(self):
        self.assertEqual(errors("fn f(n: Int) -> Int { return f(n + 1) + 1 }"), ["E0702"])
        self.assertEqual(errors("fn f(n: Int) -> Int { let x = f(n)\n if n > 0 { return x }\n return 0 }"), ["E0702"])
        self.assertEqual(errors("fn f(n: Int) -> Int { if n <= 0 { return 0 }\n return f(n - 1) }"), [])

    def test_constant_contract_violation(self):
        src = "fn half(x: Int) -> Int\n requires x % 2 == 0\n{ return x / 2 }\nfn main() uses io { print(half(3)) }"
        self.assertEqual(errors(src), ["E0703"])
        self.assertEqual(errors(src.replace("half(3)", "half(4)")), [])

    def test_builtin_domain(self):
        self.assertEqual(errors("fn main() uses io { print(2.pow(-1)) }"), ["E0704"])
        self.assertEqual(errors("fn main() uses io { print((-4.0).sqrt()) }"), ["E0704"])
        self.assertEqual(errors("fn main() uses io { print([1, 2].chunks(0)) }"), ["E0704"])

    def test_index_always_out_of_bounds(self):
        self.assertEqual(errors("fn f(xs: List[Int]) -> Option[Int] { return xs.get(xs.len()) }"), ["E0705"])
        self.assertEqual(errors("fn f(xs: List[Int]) -> Option[Int] { return xs.get(-1) }"), ["E0705"])
        self.assertEqual(errors("fn f(xs: List[Int]) -> Option[Int] { return xs.get(xs.len() - 1) }"), [])

    def test_sort_needs_ordered_values(self):
        self.assertEqual(errors("type P { x: Int }\nfn main() uses io { print([P { x: 1 }].sort()) }"), ["E0215"])
        self.assertEqual(errors("type P { x: Int }\nfn main() uses io { print([P { x: 1 }].sort_by(fn(p) => p.x)) }"),
                         [])


class Documentation(unittest.TestCase):
    def test_guide_examples_compile_and_pass(self):
        """Every ```klar block in the guides is a complete program that type-checks and whose tests pass."""
        for name in ("GUIDE.md", "GUIDE.en.md"):
            with open(os.path.join(ROOT, "docs", name), encoding="utf-8") as f:
                blocks = re.findall(r"```klar\n(.*?)```", f.read(), re.S)
            self.assertGreaterEqual(len(blocks), 7)
            for i, src in enumerate(blocks):
                with tempfile.TemporaryDirectory() as d:
                    path = os.path.join(d, f"example{i}.klar")
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(src)
                    code, out, err = cli("test", path)
                    self.assertEqual(code, 0, f"{name} block {i}:\n{src}\n{out}{err}")


class DeveloperTools(unittest.TestCase):
    def test_fmt_is_stable_on_the_repository_and_canonicalizes(self):
        import glob
        from klar.tools.fmt import format_checked
        for path in glob.glob(os.path.join(ROOT, "**", "*.klar"), recursive=True):
            if "build" in path:
                continue
            with open(path, encoding="utf-8") as f:
                src = f.read()
            self.assertEqual(format_checked(src), src, path)
        messy = "fn  add( a:Int,b :Int )->Int{\nreturn a+b\n}\nfn main()uses io{\nprint(add(1,-2))\n}\n"
        self.assertEqual(format_checked(messy), "fn add(a: Int, b: Int) -> Int {\n  return a + b\n}\n\n"
                                                "fn main() uses io {\n  print(add(1, -2))\n}\n")

    def test_eval(self):
        from klar.tools.runtools import evaluate
        r = evaluate(['"a,b".split(",")'])
        self.assertEqual((r["value"], r["type"]), ('["a", "b"]', "List[Str]"))
        r = evaluate(["let xs = [3, 1]", "xs.sort()"])
        self.assertEqual(r["value"], "[1, 3]")
        r = evaluate(["gcd(12, 18)"], os.path.join(ROOT, "klar", "std", "math.klar"))
        self.assertEqual(r["value"], "6")
        self.assertFalse(evaluate(["nope + 1"])["ok"])

    def test_outline_doc_refs(self):
        from klar.tools.inspect import doc_lookup, name_occurrences, outline
        loaded = load_path(os.path.join(ROOT, "examples", "bank.klar"))
        items = outline(loaded)[0]["items"]
        self.assertIn("fn withdraw(acc: Account, amount: Int) -> Result[Account, BankError]",
                      next(i["signature"] for i in items if i["name"] == "withdraw"))
        occ = name_occurrences(loaded, "withdraw")
        self.assertEqual([r for _, _, r in occ].count("definition"), 1)
        self.assertGreaterEqual(len(occ), 3)
        res = doc_lookup("split")
        self.assertEqual(res[0]["name"], "Str.split")
        self.assertTrue(res[0]["examples"])

    def test_new_rename_coverage_view(self):
        from klar.tools.inspect import rename
        from klar.tools.runtools import coverage, new_project
        from klar.tools.view import collect
        with tempfile.TemporaryDirectory() as d:
            proj = os.path.join(d, "demo")
            new_project(proj)
            main = os.path.join(proj, "main.klar")
            code, out, err = cli("test", main)
            self.assertEqual(code, 0, out + err)
            files, occ = rename(load_path(main), "greeting", "make_greeting")
            for path, text in files.items():
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
            self.assertFalse(load_path(main).has_errors())
            self.assertEqual(len(occ), 4)
            rep = coverage(main)
            self.assertEqual(rep["percent"], 100.0)
            data = collect(load_path(main))
            self.assertEqual(data["functions"]["main"]["calls"], ["make_greeting"])
            self.assertEqual(data["functions"]["make_greeting"]["flow"][0]["kind"], "return")


class Modules(unittest.TestCase):
    def write(self, d, name, text):
        path = os.path.join(d, *name.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def test_import_and_run(self):
        with tempfile.TemporaryDirectory() as d:
            self.write(d, "lib/geo.klar", "type P { x: Int }\nfn helper(n: Int) -> Int { return n * 2 }\n"
                                          "fn double_x(p: P) -> Int { return helper(p.x) }\nconst K: Int = 7\n")
            main = self.write(d, "main.klar", "use lib.geo.{P, double_x, K}\nuse std.math.{gcd}\n"
                                              "fn main() uses io { print(P { x: 4 }.double_x() + K + gcd(9, 6)) }\n")
            code, out, err = cli("run", main)
            self.assertEqual((code, out), (0, "18\n"), err)

    def test_private_names_need_import(self):
        with tempfile.TemporaryDirectory() as d:
            self.write(d, "a.klar", "type P { x: Int }\nfn make() -> P { return P { x: 1 } }\n")
            main = self.write(d, "main.klar", "use a.{make}\nfn main() uses io { let p = P { x: 2 }\n print(p.x) }\n")
            loaded = load_path(main)
            self.assertIn("E0104", [x.code for x in loaded.diags])
            # field access on a value of a non-imported type is fine
            main2 = self.write(d, "m2.klar", "use a.{make}\nfn main() uses io { print(make().x) }\n")
            self.assertEqual(cli("run", main2)[1], "1\n")

    def test_module_errors(self):
        with tempfile.TemporaryDirectory() as d:
            self.write(d, "a.klar", "use b.{g}\nfn f() -> Int { return g() }\n")
            self.write(d, "b.klar", "use a.{f}\nfn g() -> Int { return f() }\n")
            main = self.write(d, "main.klar", "use a.{f}\nuse nope.{x}\nuse b.{zzz}\nfn main() { }\n")
            got = [x.code for x in load_path(main).diags]
            for code in ("E0602", "E0601", "E0603"):
                self.assertIn(code, got)

    def test_type_names_unique_across_modules(self):
        with tempfile.TemporaryDirectory() as d:
            self.write(d, "a.klar", "type P { x: Int }\n")
            main = self.write(d, "main.klar", "use a.{P}\ntype P { y: Int }\nfn main() { }\n")
            self.assertIn("E0101", [x.code for x in load_path(main).diags])


class Testing(unittest.TestCase):
    def test_property_finds_and_shrinks_counterexample(self):
        loaded = load_source('property "nonneg" (xs: List[Int]) { assert xs.sum() >= 0 }', "t.klar")
        it = Interpreter(loaded, out=io.StringIO())
        with self.assertRaises(KlarRuntimeError) as ctx:
            run_with_big_stack(lambda: it.run_test(it.tests[0], runs=100, seed=0))
        self.assertEqual(ctx.exception.code, "R0010")
        self.assertIn("xs = [-1]", ctx.exception.details)

    def test_property_input_types(self):
        self.assertIn("E0605", errors('property "p" (f: fn(Int) -> Int) { }'))

    def test_doctests(self):
        loaded = load_source("/// >>> assert twice(2) == 4\n/// >>> assert twice(0) == 1\n"
                             "fn twice(n: Int) -> Int { return n * 2 }", "t.klar")
        it = Interpreter(loaded, out=io.StringIO())
        self.assertEqual([t.name for t in it.tests], ["doc: twice"])
        with self.assertRaises(KlarRuntimeError) as ctx:
            run_with_big_stack(lambda: it.run_test(it.tests[0]))
        self.assertEqual(ctx.exception.span.line, 2)

    def test_json_test_output(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.klar")
            with open(p, "w") as f:
                f.write('test "a" { assert 1 + 1 == 3 }\n')
            code, out, _ = cli("test", "--json", p)
            data = json.loads(out)
            self.assertEqual(code, 1)
            self.assertEqual(data["tests"][0]["error"]["values"], ["left = 2", "right = 3"])


class AiLoopTools(unittest.TestCase):
    def test_fix_applies_safe_fixes(self):
        src = """fn area(w: Float, h: Float, scale: Float) -> Float {
  return w * h * scale
}
fn main() uses io {
  let xs = [3, 1, 2]
  let n = xs.length()
  let total = 0
  total = total + area(1.0, 2.0, 3.0).round();
  xs.push(4)
  print(-5.abs() + n + total && true)
}
"""
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.klar")
            with open(p, "w") as f:
                f.write(src)
            code, out, _ = cli("fix", "--json", p)
            data = json.loads(out)
            fixed = sorted({a["code"] for a in data["applied"]})
            for c in ("E0001", "E0003", "E0204", "E0207", "E0208", "E0405"):
                self.assertIn(c, fixed)
            with open(p) as f:
                text = f.read()
            self.assertIn("var xs", text)
            self.assertIn("xs = xs.push(4)", text)
            self.assertIn("area(w: 1.0, h: 2.0, scale: 3.0)", text)
            self.assertIn("(-5).abs()", text)
            self.assertIn("xs.len()", text)
            # the remaining error (`Int and Bool`) needs a human/AI decision
            self.assertEqual(code, 1)
            self.assertEqual([r["code"] for r in data["remaining"] if r["code"].startswith("E")], ["E0202"])

    def test_fix_never_applies_guesses_by_default(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.klar")
            with open(p, "w") as f:
                f.write("fn main() uses io { let value = 1\n print(valeu) }\n")
            cli("fix", p)
            with open(p) as f:
                self.assertIn("valeu", f.read())
            cli("fix", "--all", p)
            with open(p) as f:
                self.assertIn("print(value)", f.read())

    def test_dev_reports_everything_in_one_call(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.klar")
            with open(p, "w") as f:
                f.write('fn double(x: Int) -> Int { return x * 2 }\n'
                        'test "ok" { assert double(2) == 4 }\n'
                        'test "bad" { assert double(2) == 5 }\n'
                        'fn main() uses io { print(double(21)) }\n')
            code, out, _ = cli("dev", "--json", p)
            data = json.loads(out)
            self.assertEqual(code, 1)
            self.assertEqual(data["tests"]["passed"], 1)
            self.assertEqual(data["tests"]["failed"][0]["values"], ["left = 4", "right = 5"])
            self.assertEqual(data["run"]["stdout"], "42\n")
            self.assertEqual(data["next"], "fix 1 failing test(s)")


class Profiling(unittest.TestCase):
    def test_profile_counts_calls(self):
        loaded = load_source("""
fn fib(n: Int) -> Int { if n < 2 { return n }
 return fib(n - 1) + fib(n - 2) }
fn main() uses io { print(fib(10)) }""", "t.klar")
        it = Interpreter(loaded, out=io.StringIO())
        it.prof = Profiler()
        run_with_big_stack(it.run_main)
        calls = {k.split(" ")[0]: v[0] for k, v in it.prof.funcs.items()}
        self.assertEqual(calls["fib"], 177)
        self.assertEqual(calls["main"], 1)
        self.assertTrue(it.prof.lines)

    def test_profile_cli_json(self):
        code, out, _ = cli("profile", "--json", os.path.join(ROOT, "examples", "shapes.klar"))
        data = json.loads(out)
        self.assertEqual(code, 0)
        self.assertTrue(any(f["function"].startswith("area") for f in data["functions"]))


class Diagnostics(unittest.TestCase):
    def check_code(self, src, code):
        got = codes(src)
        self.assertIn(code, got, f"expected {code}, got {got}")

    def test_foreign_operators(self):
        self.check_code("fn f(a: Bool, b: Bool) -> Bool { return a && b }", "E0001")
        self.check_code("fn f() -> Int { return 1; }", "E0001")
        self.check_code("fn f(a: Bool) -> Bool { return !a }", "E0001")

    def test_syntax_hints(self):
        self.check_code("fn f(xs: List[Int]) -> Int { return xs[0] }", "E0003")
        self.check_code("fn f() -> Int { let x = if true { 1 } else { 2 }\n return x }", "E0003")
        self.check_code("fn f() -> Int { let x = null\n return 1 }", "E0201")
        self.check_code("fn f() { fn g() { } }", "E0003")
        self.check_code("fn f() -> Int { return -5.abs() }", "E0003")
        self.check_code("use std.math.*", "E0003")

    def test_types(self):
        self.check_code("fn f() -> Int { return 1.5 }", "E0202")
        self.check_code("fn f() -> Float { return 1 + 2.0 }", "E0211")
        self.check_code("fn f(x: Strng) { }", "E0104")
        self.check_code("fn f(x: List) { }", "E0105")
        self.check_code("type point { x: Int }", "E0103")
        self.check_code("type Loop = Loop", "E0104")

    def test_names(self):
        self.check_code("fn f() -> Int { return y }", "E0201")
        self.check_code("fn f() { let x = 1\n let x = 2 }", "E0102")
        self.check_code("fn f() { let x = 1\n x = 2 }", "E0207")
        self.check_code("fn f() { let unused = 1 }", "W0402")
        self.check_code("const LIMIT: Int = 1\nfn f() { let LIMIT = 2 }", "E0102")

    def test_effects(self):
        self.check_code("fn f() { print(1) }", "E0401")
        self.check_code("fn f() uses iox { }", "E0403")
        self.check_code("fn f(x: Int) -> Int\n requires now_ms() > 0\n{ return x }", "E0401")
        self.check_code('test "t" { assert now_ms() > 0 }', "E0401")
        self.check_code("fn f() uses time { let g = fn() => print(1)\n g() }", "E0401")

    def test_results_and_mutation(self):
        self.check_code("fn g() -> Result[Int, Str] { return Ok(1) }\nfn f() { g() }", "E0402")
        self.assertEqual(errors("fn g() -> Result[Int, Str] { return Ok(1) }\nfn f() { let _ = g() }"), [])
        self.check_code("fn f() { let xs = [1]\n xs.push(2) }", "E0405")
        self.check_code("type P { x: Int }\nfn f() { var p = P { x: 1 }\n p.x = 2 }", "E0207")

    def test_question_mark(self):
        self.check_code("fn f() -> Int { let x = \"1\".to_int()?\n return x }", "E0212")
        self.check_code("fn g() -> Result[Int, Int] { return Ok(1) }\n"
                        "fn f() -> Result[Int, Str] { let x = g()?\n return Ok(x) }", "E0212")

    def test_match(self):
        self.check_code("enum C { R, G }\nfn f(c: C) -> Int { return match c { C.R => 1 } }", "E0301")
        self.check_code("fn f(x: Int) -> Int { return match x { 1 => 1 } }", "E0301")
        self.check_code("fn f(x: Option[Int]) -> Int { return match x { Some(v) => v } }", "E0301")
        self.check_code("enum C { R, G }\nfn f(c: C) -> Int { return match c { C.R => 1, C.B => 2, _ => 3 } }", "E0302")
        self.check_code("fn f(x: Int) -> Int { return match x { _ => 1, 2 => 2 } }", "W0303")

    def test_calls(self):
        self.check_code("fn g(a: Int, b: Int, c: Int) -> Int { return a }\nfn f() -> Int { return g(1, 2, 3) }", "E0208")
        self.check_code("fn g(a: Int) -> Int { return a }\nfn f() -> Int { return g(1, 2) }", "E0206")
        self.check_code("fn g(a: Int) -> Int { return a }\nfn f() -> Int { return g(b: 1) }", "E0209")
        self.check_code("type P { x: Int, y: Int }\nfn f() -> P { return P { x: 1 } }", "E0209")
        self.check_code("fn f(xs: List[Int]) -> Int { return xs.size() }", "E0204")
        self.check_code("fn f(xs: List[Int]) -> Int { return xs.len }", "E0203")

    def test_missing_return(self):
        self.check_code("fn f(x: Int) -> Int { if x > 0 { return 1 } }", "E0205")
        self.assertEqual(errors("fn f(x: Int) -> Int { if x > 0 { return 1 } else { return 2 } }"), [])
        self.assertEqual(errors("fn f(x: Int) -> Int { fail(\"no\") }"), [])
        self.assertEqual(errors("fn f(n: Int) -> Int {\n var i = 0\n while true {\n if i * i >= n { return i }\n"
                                " i = i + 1\n }\n}"), [])

    def test_loops(self):
        self.check_code("fn f() { break }", "E0213")
        self.check_code("fn f(m: Map[Str, Int]) { for k in m { } }", "E0202")

    def test_main_signature(self):
        self.check_code("fn main(x: Int) { }", "E0502")


if __name__ == "__main__":
    unittest.main()
