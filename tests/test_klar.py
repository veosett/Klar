"""Compiler test-suite. Run: python -m unittest discover -s tests"""
import io
import json
import os
import re
import subprocess
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
                                                  "features.klar", "effects.klar")
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
        for name in ("hello", "bank", "collections", "shapes", "features", "effects"):
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

    def test_exit_code_on_every_backend(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "ex.klar")
            with open(path, "w", encoding="utf-8") as f:
                f.write('fn main() uses io {\n  print("before")\n  exit(3)\n}\n')
            for flag in (["--interp"], ["--py"], []):
                code, out, err = cli("run", *flag, path)
                self.assertEqual((code, out), (3, "before\n"), (flag, err))

    def test_bytes_files_on_every_backend(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "b.klar")
            data = os.path.join(d, "data.bin").replace("\\", "/")
            with open(path, "w", encoding="utf-8") as f:
                f.write('fn main() uses io, fs {\n  var b = bytes_of([0, 255])\n  for i in range(0, 300) {\n'
                        '    b = b.push(i % 256)\n  }\n'
                        f'  match write_bytes("{data}", b) {{\n    Ok(_) => print("ok"),\n    Err(e) => print(e),\n  }}\n'
                        f'  let back = read_bytes("{data}")\n  print(back.map(fn(x) => x.len()))\n'
                        '  print(back == Ok(b))\n  print(read_bytes("/klar/missing/file").is_err())\n}\n')
            for flag in (["--interp"], ["--py"], []):
                code, out, err = cli("run", *flag, path)
                self.assertEqual((code, out), (0, "ok\nOk(302)\ntrue\ntrue\n"), (flag, err))
                with open(os.path.join(d, "data.bin"), "rb") as f:
                    self.assertEqual(f.read()[:4], bytes([0, 255, 0, 1]))

    @unittest.skipIf(os.name == "nt", "uses sh and chmod")
    def test_processes_on_every_backend(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "p.klar")
            script = os.path.join(d, "s.sh").replace("\\", "/")
            with open(script, "w", encoding="utf-8") as f:
                f.write("#!/bin/sh\nexit 7\n")
            with open(path, "w", encoding="utf-8") as f:
                f.write('fn main() uses io, fs, proc {\n  print(run_command(["sh", "-c", "exit 4"]))\n'
                        f'  print(run_command(["{script}"]))\n  print(set_executable("{script}"))\n'
                        f'  print(run_command(["{script}"]))\n  print(run_command(["klar-not-a-program-42"]))\n'
                        '  print(set_executable("/klar/missing/file").is_err())\n}\n')
            want = ("Ok(4)\nOk(127)\nOk(())\nOk(7)\n"
                    "Err(\"cannot run 'klar-not-a-program-42': No such file or directory\")\ntrue\n")
            for flag in (["--interp"], ["--py"], []):
                os.chmod(script, 0o644)
                code, out, err = cli("run", *flag, path)
                self.assertEqual((code, out), (0, want), (flag, err))

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

    def test_read_exact(self):
        out = run("""
fn main() uses io {
  print(read_exact(3))
  print(read_line())
  print(read_exact(10))
  print(read_exact(1))
}""", stdin="abcdef\nxy")
        self.assertEqual(out, 'Some("abc")\nSome("def")\nSome("xy")\nNone\n')

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

    def test_eprint_goes_to_stderr(self):
        from klar.native.build import build, host_target
        src = 'fn main() uses io {\n  print_raw("o")\n  print("ut")\n  eprint("err {1 + 1}")\n  eprint([1, 2])\n}\n'
        loaded = load_source(src, "t.klar")
        for runner in (Interpreter, CompiledProgram):
            out, err = io.StringIO(), io.StringIO()
            run_with_big_stack(runner(loaded, out=out, inp=io.StringIO(""), err_stream=err, cli_args=()).run_main)
            self.assertEqual((out.getvalue(), err.getvalue()), ("out\n", "err 2\n[1, 2]\n"))
        if host_target() == "linux":
            with tempfile.TemporaryDirectory() as d:
                path, exe = os.path.join(d, "t.klar"), os.path.join(d, "t")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(src)
                build(path, out=exe, target="linux")
                r = subprocess.run([exe], capture_output=True, text=True)
                self.assertEqual((r.stdout, r.stderr), ("out\n", "err 2\n[1, 2]\n"))

    def test_directories(self):
        from klar.native.build import build, host_target
        src = """
fn main() uses io, fs {{
  print(list_dir("{d}"))
  print(list_dir("{d}/missing").is_err())
  print(list_dir("{d}/b.txt"))
  print([is_dir("{d}"), is_dir("{d}/sub"), is_dir("{d}/b.txt"), is_dir("{d}/nope")])
  print(make_dir("{d}/x/y/z"))
  print([is_dir("{d}/x/y/z"), make_dir("{d}/b.txt").is_err()])
  print([write_file("{d}/x/gone.txt", "x").is_ok(), remove_file("{d}/x/gone.txt").is_ok(), file_exists("{d}/x/gone.txt")])
  print(remove_file("{d}/x/gone.txt"))
  print(current_dir().len() > 1)
}}"""
        with tempfile.TemporaryDirectory() as d:
            for name in ("b.txt", "a.klar", "é.txt"):
                with open(os.path.join(d, name), "w") as f:
                    f.write("x")
            os.mkdir(os.path.join(d, "sub"))
            root = d.replace("\\", "/")
            want = (f'Ok(["a.klar", "b.txt", "sub", "é.txt"])\ntrue\n'
                    f'Err("cannot list \'{root}/b.txt\': Not a directory")\n[true, true, false, false]\nOk(())\n[true, true]\n'
                    f'[true, true, false]\nErr("cannot remove \'{root}/x/gone.txt\': No such file or directory")\ntrue\n')
            program = src.format(d=root)
            import shutil
            for compiled in (False, True):
                out, ex = _run_backend(load_source(program, "t.klar"), compiled, "", ())
                shutil.rmtree(os.path.join(d, "x"), ignore_errors=True)
                self.assertIsNone(ex)
                self.assertEqual(out, want)
            if host_target() == "linux":
                with tempfile.TemporaryDirectory() as b:
                    path, exe = os.path.join(b, "t.klar"), os.path.join(b, "t")
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(program)
                    build(path, out=exe, target="linux")
                    self.assertEqual(subprocess.run([exe], capture_output=True, text=True).stdout, want)

    def test_run_capture(self):
        from klar.native.build import build, host_target
        if host_target() != "linux":
            self.skipTest("run_capture needs Linux")
        program = """
fn show(r: Result[List[Str], Str]) uses io {
  match r {
    Ok(xs) => print(xs),
    Err(e) => print("err " + e),
  }
}

fn main() uses io, proc {
  show(run_capture(args: ["sh", "-c", "echo out; echo err >&2; exit 3"], dir: "", input: ""))
  show(run_capture(args: ["pwd"], dir: "/", input: ""))
  show(run_capture(args: ["no-such-program-zz"], dir: "", input: ""))
  show(run_capture(args: ["sh", "-c", "kill -9 $$"], dir: "", input: ""))
  show(run_capture(args: ["sh", "-c", "head -c 200000 /dev/zero | tr '\\\\0' a >&2"], dir: "", input: "").map(fn(xs) => [
    xs.get_or(2, "").len().to_str()]))
  show(run_capture(args: ["tr", "a-z", "A-Z"], dir: "", input: "héllo\\nworld"))
  show(run_capture(args: [], dir: "", input: ""))
}"""
        want = ('["3", "out\\n", "err\\n"]\n["0", "/\\n", ""]\nerr cannot run \'no-such-program-zz\': No such file or '
                'directory\n["137", "", ""]\n[\"200000\"]\n[\"0\", \"HéLLO\\nWORLD\", \"\"]\nerr run_capture: no program given\n')
        for compiled in (False, True):
            out, ex = _run_backend(load_source(program, "t.klar"), compiled, "", ())
            self.assertIsNone(ex)
            self.assertEqual(out, want)
        with tempfile.TemporaryDirectory() as b:
            path, exe = os.path.join(b, "t.klar"), os.path.join(b, "t")
            with open(path, "w", encoding="utf-8") as f:
                f.write(program)
            build(path, out=exe, target="linux")
            self.assertEqual(subprocess.run([exe], capture_output=True, text=True).stdout, want)

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


class Parallelism(unittest.TestCase):
    def test_par_map_needs_a_pure_function_and_plain_results(self):
        self.assertEqual(errors("fn main() uses io { print([1].par_map(fn(i) => i + 1)) }"), [])
        self.assertEqual(errors("fn sq(i: Int) -> Int { return i * i }\nfn main() uses io { print([1].par_map(sq)) }"),
                         [])
        self.assertEqual(errors("fn main() uses io { print([1].par_map(fn(i) => now_ms() + i)) }"), ["E0401"])
        self.assertEqual(errors("fn main() uses io { print([1].par_map(fn(i) => [i].map(fn(k) => dbg(k)))) }"),
                         ["E0401"])
        self.assertEqual(errors("fn p(i: Int) -> Int uses io {\n print(i)\n return i\n}\n"
                                "fn main() uses io { print([1].par_map(p)) }"), ["E0406"])
        # a function value is pure when its type says so
        self.assertEqual(errors("fn main() uses io {\n let f = fn(i: Int) => i\n print([1].par_map(f))\n}"), [])
        self.assertEqual(errors("fn run(f: fn(Int) -> Int uses io) -> List[Int] uses io {\n return [1].par_map(f)\n}"),
                         ["E0406"])
        self.assertEqual(errors("fn main() uses io { print([1].par_map(fn(i) => fn(k: Int) => k + i).len()) }"),
                         ["E0406"])

    def test_par_map_sees_the_effects_of_function_values(self):
        """The type of a function value carries its effects, so par_map's lambda may call any function value whose
        type is pure — and none that does effects."""
        g = "fn main() uses io {\n let g = fn(n: Int) -> Int {\n print(n)\n return n\n }\n"
        apply = "fn apply(f: fn(Int) -> Int, x: Int) -> Int {\n return f(x)\n}\n"
        self.assertEqual(errors(g + " print([1].par_map(fn(x) => g(x)))\n}"), ["E0401"])
        self.assertEqual(errors(apply + g + " print([1].par_map(fn(x) => apply(g, x)))\n}"), ["E0202"])
        self.assertEqual(errors(g + " print([1].par_map(g))\n}"), ["E0406"])
        self.assertEqual(errors("fn tw(x: Int) -> Int {\n return x * 2\n}\nfn main() uses io {\n"
                                " print([tw].par_map(fn(f) => f(1)))\n}"), [])
        self.assertEqual(errors(apply + "fn tw(x: Int) -> Int {\n return x * 2\n}\nfn main() uses io {\n let k = 3\n"
                                " print([1].par_map(fn(x) => apply(tw, x) + apply(fn(y) => y + k, x)))\n}"), [])

    def test_par_map_native_matches_map_and_reports_the_first_error(self):
        from klar.native.build import build, host_target
        if host_target() != "linux":
            self.skipTest("native Linux only")
        src = ("fn f(i: Int) -> Int {\n  if i == 3 or i == 9 {\n    return fail(\"bad {i}\")\n  }\n  return i * i\n}\n\n"
               "fn main() uses io {\n  print(range(0, 3).par_map(f))\n  print(range(0, 12).par_map(f))\n}\n")
        with tempfile.TemporaryDirectory() as d:
            path, exe = os.path.join(d, "p.klar"), os.path.join(d, "p")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(src)
            build(path, out=exe, target="linux")
            got = subprocess.run([exe], capture_output=True, text=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(src.replace("par_map", "map"))
            build(path, out=exe, target="linux")
            want = subprocess.run([exe], capture_output=True, text=True)
        self.assertEqual((got.stdout, got.stderr, got.returncode), (want.stdout, want.stderr, want.returncode))
        self.assertIn("bad 3", got.stderr)
        self.assertEqual(got.stdout, "[0, 1, 4]\n")


class FunctionEffects(unittest.TestCase):
    """Function types carry effects (`fn(Int) -> Unit uses io`): a function without `uses` is pure, also when it
    calls function values."""
    NOISY = "fn noisy(x: Int) -> Int uses io {\n print(x)\n return x\n}\n"
    APPLY = "fn apply(f: fn(Int) -> Int, x: Int) -> Int {\n return f(x)\n}\n"

    def test_calling_a_function_value_needs_its_effects(self):
        self.assertEqual(errors("fn f(g: fn(Int) -> Unit uses io) {\n g(1)\n}"), ["E0401"])
        self.assertEqual(errors("fn f(g: fn(Int) -> Unit uses io) uses io {\n g(1)\n}"), [])
        self.assertEqual(errors("fn f(g: fn() -> Int uses time, rand) -> Int uses time {\n return g()\n}"),
                         ["E0401"])

    def test_effectful_functions_do_not_fit_pure_types(self):
        self.assertEqual(errors(self.NOISY + self.APPLY + "fn main() uses io {\n print(apply(noisy, 1))\n}"),
                         ["E0202"])
        self.assertEqual(errors(self.NOISY + self.APPLY + "fn main() uses io {\n print(apply(fn(x) => noisy(x), 1))\n}"),
                         ["E0401"])
        self.assertEqual(errors(self.NOISY + "fn main() uses io {\n var g = fn(x: Int) => x\n g = noisy\n print(g(1))\n}"),
                         ["E0202"])
        d = [x for x in diags(self.NOISY + self.APPLY + "fn main() uses io {\n print(apply(noisy, 1))\n}")
             if x.code == "E0202"][0]
        self.assertIn("fn(Int) -> Int uses io", d.message)
        self.assertIn("add `uses io` to the function type", d.hint)

    def test_pure_and_smaller_effects_fit_larger_types(self):
        src = ("fn each(xs: List[Int], f: fn(Int) -> Unit uses io, fs) uses io, fs {\n for x in xs {\n f(x)\n }\n}\n"
               "fn show(x: Int) uses io {\n print(x)\n}\n"
               "fn main() uses io, fs {\n each([1, 2], show)\n each([3], fn(x) => print(x * 10))\n"
               " each([4], fn(_x) {\n })\n}")
        self.assertEqual(run(src), "1\n2\n30\n")

    def test_lambdas_take_the_effects_of_the_written_type(self):
        src = ("fn make(p: Str) -> (fn(Str) -> Unit uses io) {\n return fn(m) => print(\"{p}{m}\")\n}\n"
               "fn main() uses io {\n let f = make(\">\")\n f(\"hi\")\n}")
        self.assertEqual(run(src), ">hi\n")
        self.assertEqual(errors("fn make() -> fn() -> Unit {\n return fn() => print(1)\n}"), ["E0401"])

    def test_builtins_do_what_their_function_does(self):
        self.assertEqual(errors(self.NOISY + "fn f() -> List[Int] {\n return [1].map(noisy)\n}"), ["E0401"])
        self.assertEqual(errors(self.NOISY + "fn f() -> List[Int] uses io {\n return [1].map(noisy)\n}"), [])
        self.assertEqual(errors("fn f(g: fn(Int) -> Bool uses rand) -> List[Int] {\n return [1].filter(g)\n}"),
                         ["E0401"])

    def test_unknown_effect_in_a_function_type(self):
        self.assertEqual(errors("fn f(g: fn() -> Unit uses iox) {\n}"), ["E0403"])

    def test_function_type_syntax(self):
        # a comma after the effects starts the next parameter when a `name:` follows
        self.assertEqual(errors("fn f(g: fn() -> Unit uses io, fs: Int) uses io {\n g()\n print(fs)\n}"), [])
        self.assertEqual(errors("type Job {\n run: fn() -> Unit uses io, fs\n}\n"
                                "fn go(j: Job) uses io, fs {\n j.run()\n}"), [])
        self.assertEqual(errors("type Job {\n run: fn() -> Unit uses io\n}\nfn go(j: Job) {\n j.run()\n}"),
                         ["E0401"])


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

    def test_contracts_checked_with_known_signs(self):
        lib = ("fn root(n: Int) -> Int\n  requires n >= 0\n{\n  return n\n}\n\n"
               "fn first(xs: List[Int]) -> Int\n  requires not xs.is_empty()\n{\n  return xs.get_or(0, 0)\n}\n\n"
               "pub fn size(n: Int) -> Int\n  ensures result > 0\n{\n  if n > 0 {\n    return n\n  }\n  return BODY\n}\n\n")

        def errs(call, body="1"):
            return errors(lib.replace("BODY", body) + "pub fn g(n: Int, xs: List[Int]) -> Int {\n" + call + "\n}\n")
        self.assertEqual(errs("  if n < 0 {\n    return root(n)\n  }\n  return root(n)"), ["E0703"])
        self.assertEqual(errs("  if xs.is_empty() {\n    return first(xs)\n  }\n  return first(xs)"), ["E0703"])
        self.assertEqual(errs("  return first([])"), ["E0703"])
        self.assertEqual(errs("  return root(n) + first(xs) + root(n * n) + first([n])"), [])
        self.assertEqual(errs("  return 0", body="0"), ["E0706"])
        self.assertEqual(errs("  return 0", body="-n"), [])           # n <= 0 here: -n >= 0, not proven > 0
        d = [x for x in diags(lib.replace("BODY", "0")) if x.code == "E0706"][0]
        self.assertEqual(d.hint, "here the result is 0")

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


    def test_every_diagnostic_code_is_explained(self):
        """`klar explain` knows every code that the compilers and the runtime can report."""
        import glob
        from klar.diagnostics import CODES
        used = set()
        files = glob.glob(os.path.join(ROOT, "klar", "**", "*.py"), recursive=True)
        files += glob.glob(os.path.join(ROOT, "klar", "rt", "*.klar"))
        files += glob.glob(os.path.join(ROOT, "compiler", "*.klar"))
        for path in files:
            if path.endswith(("diagnostics.py", "builtin_sigs.klar")):
                continue
            with open(path, encoding="utf-8") as f:
                used |= set(re.findall(r"[\"(]([EWR]0\d{3})[\")]", f.read()))
        missing = sorted(c for c in used - set(CODES) if c not in ("R0099", "E0000", "R0000"))
        self.assertEqual(missing, [], "codes without an explanation in klar/diagnostics.py")

    def test_spec_examples_and_versions(self):
        """docs/SPEC.md and its translation describe the current version and keep the same sections."""
        from klar import __version__
        major_minor = ".".join(__version__.split(".")[:2])
        heads = []
        for name in ("SPEC.md", "SPEC.en.md"):
            with open(os.path.join(ROOT, "docs", name), encoding="utf-8") as f:
                text = f.read()
            self.assertTrue(text.startswith(f"# Klar {major_minor} "), name)
            heads.append(re.findall(r"^## (\d+)\.", text, re.M))
        self.assertEqual(heads[0], heads[1])
        with open(os.path.join(ROOT, "klar", "ai_reference.md"), encoding="utf-8") as f:
            self.assertTrue(f.read().startswith(f"# Klar {major_minor} "))


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
        # re-indenting a line moves the code inside its interpolated strings: still the same program
        shifted = "fn main() uses io {\nprint(\"{1 + 2}\")\n}\n"
        self.assertEqual(format_checked(shifted), "fn main() uses io {\n  print(\"{1 + 2}\")\n}\n")

    def test_patch(self):
        import tempfile
        from klar.tools.patch import patch_file
        src = ("/// Doubles a number.\nfn double(x: Int) -> Int {\n  return x * 2\n}\n\n"
               "fn main() uses io {\n  print(double(3))\n}\n\n"
               "test \"double\" {\n  assert double(2) == 4\n}\n")
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "m.klar")

            def reset():
                with open(path, "w", encoding="utf-8") as f:
                    f.write(src)

            def text():
                with open(path, encoding="utf-8") as f:
                    return f.read()
            reset()
            # replace by name keeps the doc comment; insert after; find in a declaration
            r = patch_file(path, {"edits": [
                {"replace": "double", "with": "fn double(x: Int) -> Int {\n  return x + x\n}"},
                {"insert": "fn triple(x: Int) -> Int {\n  return x * 3\n}", "after": "double"},
                {"find": "double(3)", "replace": "triple(3)", "in": "main"}], "test": True})
            self.assertTrue(r["ok"] and r["written"], r)
            self.assertEqual(r["tests"]["passed"], 1)
            out = text()
            self.assertIn("/// Doubles a number.\nfn double(x: Int) -> Int {\n  return x + x\n}", out)
            self.assertIn("fn triple", out)
            self.assertIn("print(triple(3))", out)
            # a type error: nothing is written
            reset()
            r = patch_file(path, {"edits": [{"replace": "double", "with": "fn double(x: Int) -> Int {\n"
                                                                          "  return \"no\"\n}"}]})
            self.assertFalse(r["ok"] or r["written"])
            self.assertTrue(r["errors"])
            self.assertEqual(text(), src)
            # a failing test rejects the patch
            r = patch_file(path, {"edits": [{"replace": "double", "with": "fn double(x: Int) -> Int {\n"
                                                                          "  return x * 3\n}"}], "test": True})
            self.assertFalse(r["ok"])
            self.assertEqual(r["tests"]["failed"][0]["name"], "double")
            self.assertEqual(text(), src)
            # unknown targets suggest a name; overlapping edits are refused
            r = patch_file(path, {"edits": [{"delete": "doubel"}]})
            self.assertIn("did you mean `double`", r["error"])
            r = patch_file(path, {"edits": [{"delete": "double"}, {"find": "x * 2", "replace": "x"}]})
            self.assertIn("same part", r["error"])
            # rename everywhere, delete a test, replace a node by id (dry run)
            r = patch_file(path, {"edits": [{"rename": "double", "to": "twice"}, {"delete": "test:double"}]})
            self.assertTrue(r["ok"], r)
            self.assertNotIn("double", text())
            self.assertNotIn("test ", text())
            reset()
            from klar import nodes as N
            from klar.parser import parse
            ids = N.number(parse(src, "m.klar"))
            lit = next(i for i, n in ids.items() if isinstance(n, N.IntLit) and n.value == 3)
            r = patch_file(path, {"edits": [{"id": lit, "with": "5"}]}, write=False)
            self.assertTrue(r["ok"] and not r["written"])
            self.assertIn("+  print(double(5))", r["diff"])
            self.assertEqual(text(), src)

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


class Exhaustiveness(unittest.TestCase):
    ENUM = "enum Shape {\n  Circle(r: Int),\n  Rect(w: Int, h: Int),\n}\n\n"

    def messages(self, body):
        return [(d.code, d.message) for d in diags(self.ENUM + body)]

    def test_nested_patterns_are_checked(self):
        got = self.messages("fn f(x: Option[Shape]) -> Int {\n  return match x {\n    Some(Shape.Circle(_)) => 1,\n"
                            "    None => 0,\n  }\n}\n")
        self.assertTrue(any(c == "E0301" and "Some(Shape.Rect(_, _))" in m for c, m in got), got)
        got = self.messages("fn f(x: Option[Option[Bool]]) -> Int {\n  return match x {\n    Some(Some(true)) => 1,\n"
                            "    None => 2,\n  }\n}\n")
        msg = next(m for c, m in got if c == "E0301")
        self.assertIn("Some(None)", msg)
        self.assertIn("Some(Some(false))", msg)

    def test_complete_nested_match_needs_no_catch_all(self):
        self.assertEqual(errors(self.ENUM + "fn f(x: Option[Shape]) -> Int {\n  return match x {\n"
                                            "    Some(Shape.Circle(_)) => 1,\n    Some(Shape.Rect(_, _)) => 2,\n"
                                            "    None => 0,\n  }\n}\n"), [])

    def test_unreachable_arms(self):
        got = codes(self.ENUM + "fn f(x: Option[Bool]) -> Int {\n  return match x {\n    Some(true) => 1,\n"
                                "    Some(false) => 2,\n    Some(_) => 3,\n    None => 4,\n  }\n}\n")
        self.assertIn("W0303", got)
        self.assertNotIn("E0301", got)


class Traits(unittest.TestCase):
    BASE = """trait Shape {
  fn area(self) -> Float
  fn label(self) -> Str {
    return "area {self.area()}"
  }
}

type Sq { side: Float }

type Circle { r: Float }

impl Shape for Sq {
  fn area(self) -> Float {
    return self.side * self.side
  }
}

impl Shape for Circle {
  fn area(self) -> Float {
    return 3.0 * self.r * self.r
  }
  fn label(self) -> Str {
    return "circle"
  }
}

fn total[T: Shape](xs: List[T]) -> Float {
  return xs.map(fn(s) => s.area()).sum_float()
}
"""

    def test_static_dispatch_defaults_and_overrides(self):
        src = self.BASE + """
fn labels[T: Shape](xs: List[T]) -> List[Str] {
  return xs.map(fn(s) => s.label())
}

fn main() uses io {
  print(total([Sq { side: 2.0 }, Sq { side: 1.0 }]))
  print(total([Circle { r: 1.0 }]))
  print(labels([Sq { side: 3.0 }]))
  print(labels([Circle { r: 1.0 }]))
  print(Sq { side: 1.0 }.label())
}
"""
        self.assertEqual(run(src), "5.0\n3.0\n[\"area 9.0\"]\n[\"circle\"]\narea 1.0\n")

    def test_impls_for_builtin_types_and_enums(self):
        src = """trait Describe {
  fn describe(self) -> Str
}

enum Light {
  Red,
  Green,
}

impl Describe for Int {
  fn describe(self) -> Str {
    return "int {self}"
  }
}

impl Describe for Light {
  fn describe(self) -> Str {
    return match self {
      Light.Red => "stop",
      Light.Green => "go",
    }
  }
}

fn all[T: Describe](xs: List[T]) -> Str {
  return xs.map(fn(x) => x.describe()).join(", ")
}

fn main() uses io {
  print(all([1, 2]))
  print(all([Light.Red, Light.Green]))
}
"""
        self.assertEqual(run(src), "int 1, int 2\nstop, go\n")

    def test_trait_errors(self):
        def errs(extra):
            return errors(self.BASE + extra)
        self.assertIn("E0220", errs("type P { x: Int }\nfn f() -> Float {\n  return total([P { x: 1 }])\n}\n"))
        self.assertIn("E0220", errs("fn f[U](xs: List[U]) -> Float {\n  return total(xs)\n}\n"))
        self.assertIn("E0223", errs("fn f() -> Float {\n  return total([])\n}\n"))
        self.assertIn("E0224", errs("fn f(s: Shape) -> Int {\n  return 1\n}\n"))
        self.assertIn("E0204", errs("fn f[T](x: T) -> Float {\n  return x.area()\n}\n"))
        self.assertIn("E0222", errs("impl Shape for Sq {\n  fn area(self) -> Float {\n    return 0.0\n  }\n}\n"))
        self.assertIn("E0221", errs("type P { x: Int }\nimpl Shape for P {\n}\n"))
        self.assertIn("E0221", errs("type P { x: Int }\nimpl Shape for P {\n  fn area(self) -> Int {\n"
                                    "    return 1\n  }\n}\n"))
        self.assertIn("E0221", errs("type P { x: Int }\nimpl Shape for P {\n  fn area(self) -> Float {\n"
                                    "    return 1.0\n  }\n  fn extra(self) -> Int {\n    return 1\n  }\n}\n"))
        self.assertIn("E0221", errs("impl Shape for List[Int] {\n  fn area(self) -> Float {\n    return 1.0\n  }\n}\n"))
        self.assertIn("E0104", errs("impl Shap for Sq {\n}\n"))
        self.assertIn("E0003", errs("trait T {\n  fn make() -> Int\n}\n"))
        self.assertIn("E0003", errs("fn f(self) -> Int {\n  return 1\n}\n"))

    def test_generic_impls(self):
        src = self.BASE + """
type Pile[T] { items: List[T] }

impl[T: Shape] Shape for Pile[T] {
  fn area(self) -> Float {
    return total(self.items)
  }
}

impl[T: Shape] Shape for List[T] {
  fn area(self) -> Float {
    return total(self)
  }
}

fn main() uses io {
  let p = Pile { items: [Sq { side: 2.0 }, Sq { side: 1.0 }] }
  print(p.area())
  print(total([p, Pile { items: [] }]))
  print([[Circle { r: 1.0 }]].label())
}
"""
        self.assertEqual(run(src), "5.0\n5.0\narea 3.0\n")
        bad = src.replace("print(p.area())", "print(total([Pile { items: [1] }]))")
        ds = [d for d in diags(bad) if d.code == "E0220"]
        self.assertEqual(len(ds), 1)
        self.assertIn("only if `Int` implements `Shape`", ds[0].hint)
        def errs(extra):
            return errors(self.BASE + "type Pile[T] { items: List[T] }\n" + extra)
        body = " {\n  fn area(self) -> Float {\n    return 1.0\n  }\n}\n"
        self.assertEqual(errs("impl[T] Shape for Pile[T]" + body), [])
        for target in ("impl Shape for Pile[Int]", "impl[T] Shape for Pile[Int]", "impl[T, U] Shape for Pile[T]",
                       "impl[T] Shape for Sq", "impl[T] Shape for Map[T, T]"):
            self.assertIn("E0221", errs(target + body), target)
        self.assertIn("E0104", errs("impl[T: Nope] Shape for Pile[T]" + body))

    def test_newtypes(self):
        src = """type Meters = new Float

type Percent = new Int
  requires value >= 0 and value <= 100

fn total(xs: List[Meters]) -> Meters {
  return Meters(xs.map(fn(m) => m.value).sum_float())
}

fn main() uses io {
  print(total([Meters(1.5), Meters(value: 2.0)]))
  print(Percent(40).value + 2)
}
"""
        self.assertEqual(run(src), "Meters { value: 3.5 }\n42\n")
        self.assertEqual(errors(src), [])
        def errs(extra):
            return errors(src.replace("fn main() uses io {", "fn main() uses io {\n" + extra))
        self.assertIn("E0217", errs("  let _a = Meters { value: 1.0 }"))
        self.assertIn("E0217", errs("  let _a = Meters(1.0) with { value: 2.0 }"))
        self.assertIn("E0703", errs("  let _a = Percent(101)"))
        ds = [d for d in diags(src.replace("fn main() uses io {", "fn main() uses io {\n  let _a: Meters = 1.0"))
              if d.code == "E0202"]
        self.assertEqual(ds[0].hint, "wrap the value: `Meters(value)`")
        ds = [d for d in diags(src.replace("fn main() uses io {", "fn main() uses io {\n  let _a: Float = Meters(1.0)"))
              if d.code == "E0202"]
        self.assertEqual(ds[0].hint, "read the wrapped value: `.value`")
        bad = src.replace("print(Percent(40).value + 2)", "let n = 140\n  print(Percent(n).value)")
        with self.assertRaises(KlarRuntimeError) as cm:
            run(bad)
        self.assertEqual(cm.exception.code, "R0002")
        # the constructor's `value` does not clash with a function named `value`, and needs no snake_case
        self.assertEqual([d.code for d in diags(src + "\nfn value() -> Int {\n  return 1\n}\n")
                          if d.code in ("E0102", "W0104")], [])

    def test_missing_methods_are_stubbed_by_fix(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "t.klar")
            with open(path, "w", encoding="utf-8") as f:
                f.write("trait Pet {\n  fn name(self) -> Str\n}\n\ntype Dog { n: Str }\n\nimpl Pet for Dog {\n}\n\n"
                        "fn main() uses io {\n  print(Dog { n: \"rex\" }.name())\n}\n")
            cli("fix", path)
            self.assertEqual([x.code for x in load_path(path).diags if x.severity == "error"], [])
            with open(path, encoding="utf-8") as f:
                self.assertIn('return todo("name")', f.read())

    def test_traits_across_modules(self):
        with tempfile.TemporaryDirectory() as d:
            for name, text in {
                "geo.klar": "pub trait Area {\n  fn area(self) -> Int\n}\n\ntype Sq { s: Int }\n\nimpl Area for Sq {\n"
                            "  fn area(self) -> Int {\n    return self.s * self.s\n  }\n}\n\n"
                            "pub fn make() -> Sq {\n  return Sq { s: 3 }\n}\n",
                "main.klar": "use geo.{Area, make}\n\ntype Rect { w: Int, h: Int }\n\nimpl Area for Rect {\n"
                             "  fn area(self) -> Int {\n    return self.w * self.h\n  }\n}\n\n"
                             "fn sum_area[T: Area](xs: List[T]) -> Int {\n  return xs.map(fn(x) => x.area()).sum()\n}"
                             "\n\nfn main() uses io {\n  print(make().area())\n  print(sum_area([Rect { w: 2, h: 5 }]))\n"
                             "}\n",
                "bad.klar": "use geo.{make}\n\nfn main() uses io {\n  print(make().area())\n}\n",
            }.items():
                with open(os.path.join(d, name), "w", encoding="utf-8") as f:
                    f.write(text)
            for flag in (["--interp"], ["--py"]):
                code, out, err = cli("run", *flag, os.path.join(d, "main.klar"))
                self.assertEqual((code, out), (0, "9\n10\n"), err)
            self.assertIn("E0104", [x.code for x in load_path(os.path.join(d, "bad.klar")).diags])

    def test_own_function_wins_when_the_trait_is_not_imported(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "a.klar"), "w", encoding="utf-8") as f:
                f.write("pub trait Describe {\n  fn describe(self) -> Str\n}\n\npub type C { x: Int }\n\n"
                        "impl Describe for C {\n  fn describe(self) -> Str {\n    return \"impl\"\n  }\n}\n")
            main = os.path.join(d, "main.klar")
            with open(main, "w", encoding="utf-8") as f:
                f.write("use a.{C}\n\nfn describe(c: C) -> Str {\n  return \"free {c.x}\"\n}\n\n"
                        "fn main() uses io {\n  print(C { x: 1 }.describe())\n}\n")
            for flag in (["--interp"], ["--py"]):
                self.assertEqual(cli("run", *flag, main)[1], "free 1\n")

    def test_tools_know_traits(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "t.klar")
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.BASE + "\nfn main() uses io {\n  print(total([Sq { side: 1.0 }]))\n}\n")
            out = cli("outline", path)[1]
            self.assertIn("trait Shape", out)
            self.assertIn("impl Shape for Circle", out)
            refs = cli("refs", path, "area")[1]
            self.assertEqual(refs.count("method definition"), 3)
            self.assertIn("method call", refs)
            self.assertIn("default method of trait `Shape`", cli("doc", "label", "--in", path)[1])


class SelfHosting(unittest.TestCase):
    def test_klar_compiler_matches_python(self):
        """compiler/*.klar give exactly the tokens, trees, diagnostics, KIR and executables of the Python compiler
        (native builds)."""
        from klar.native.build import host_target
        if host_target() != "linux":
            self.skipTest("the Klar compiler runs as a Linux x86-64 executable")
        sys.path.insert(0, os.path.join(ROOT, "tests"))
        import selfhost
        out = io.StringIO()
        old, sys.stdout = sys.stdout, out
        try:
            code = selfhost.main([])
        finally:
            sys.stdout = old
        self.assertEqual(code, 0, out.getvalue()[-3000:])

    def test_bootstrap(self):
        """klarc built by the Python compiler builds itself; stage1 == stage2 == stage3 (Linux x86-64 only)."""
        sys.path.insert(0, os.path.join(ROOT, "tests"))
        import bootstrap
        out = io.StringIO()
        old, sys.stdout = sys.stdout, out
        try:
            code = bootstrap.main()
        finally:
            sys.stdout = old
        self.assertEqual(code, 0, out.getvalue()[-3000:])


    def test_build_sh_builds_klarc_without_python(self):
        """build.sh (from a seed klarc) builds klarc twice and checks that the compiler reproduces itself."""
        import shutil
        from klar.native.build import build, host_target
        if host_target() != "linux" or not shutil.which("sh"):
            self.skipTest("Linux x86-64 only")
        with tempfile.TemporaryDirectory() as d:
            for name in ("build.sh", "pyproject.toml"):
                shutil.copy(os.path.join(ROOT, name), d)
            for name in ("compiler", "klar"):
                shutil.copytree(os.path.join(ROOT, name), os.path.join(d, name),
                                ignore=shutil.ignore_patterns("__pycache__", "*.py"))
            seed = os.path.join(d, "seed-klarc")
            build(os.path.join(ROOT, "compiler", "klarc.klar"), out=seed, target="linux")
            p = subprocess.run(["sh", os.path.join(d, "build.sh")], capture_output=True, text=True,
                               env=dict(os.environ, KLARC=seed))
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertIn("ok: build/klarc", p.stdout)
            with open(seed, "rb") as a, open(os.path.join(d, "build", "klarc"), "rb") as b:
                self.assertEqual(a.read(), b.read())


class LanguageServer(unittest.TestCase):
    GEO = ("pub trait Shape {\n  fn area(self) -> Float\n}\n\npub type Circle { r: Float }\n\nimpl Shape for Circle {\n"
           "  fn area(self) -> Float {\n    return 3.0 * self.r * self.r\n  }\n}\n\n"
           "pub fn unit() -> Circle {\n  return Circle { r: 1.0 }\n}\n\nfn hidden() -> Int {\n  return 1\n}\n")
    MAIN = ("use geo.{Shape, Circle, unit, hidden}\n\n/// Sum of areas.\nfn total[T: Shape](xs: List[T]) -> Float {\n"
            "  return xs.map(fn(s) => s.area()).sum_float()\n}\n\nfn main() uses io {\n  let c = unit()\n"
            "  let words = \"a b\".split(\" \")\n  print(total([c, Circle { r: 2.0 }]))\n  print(words.len())\n}\n")

    def session(self, requests):
        """Runs the server on framed messages; returns {id: result} and the notifications."""
        from klar.tools.lsp import Server
        data = b""
        for m in requests:
            body = json.dumps(dict(m, jsonrpc="2.0")).encode()
            data += b"Content-Length: %d\r\n\r\n" % len(body) + body
        out = io.BytesIO()
        Server(io.BytesIO(data), out, io.StringIO()).serve()
        raw, results, notes = out.getvalue(), {}, []
        while raw:
            head, _, rest = raw.partition(b"\r\n\r\n")
            n = int(head.split(b":")[1])
            msg, raw = json.loads(rest[:n]), rest[n:]
            if "id" in msg:
                results[msg["id"]] = msg.get("result", msg.get("error"))
            else:
                notes.append(msg)
        return results, notes

    def test_malformed_messages_are_skipped(self):
        """A bad header or body does not end the session (it used to crash the server)."""
        from klar.tools.lsp import Server
        good = json.dumps({"jsonrpc": "2.0", "id": 7, "method": "shutdown"}).encode()
        data = (b"Content-Length: abc\r\n\r\n" + b"Content-Length: -1\r\n\r\n" + b"Content-Length: 5\r\n\r\n{bad!"
                + b"Content-Length: 3\r\n\r\n[1]" + b"Content-Length: %d\r\n\r\n" % len(good) + good)
        out = io.BytesIO()
        Server(io.BytesIO(data), out, io.StringIO()).serve()
        self.assertIn(b'"id": 7', out.getvalue())

    def test_features(self):
        from klar.tools.lsp import path_to_uri
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "geo.klar"), "w", encoding="utf-8") as f:
                f.write(self.GEO)
            uri = path_to_uri(os.path.join(d, "main.klar"))
            doc = {"textDocument": {"uri": uri}}

            def at(line, ch):
                return dict(doc, position={"line": line, "character": ch})
            res, notes = self.session([
                {"id": 1, "method": "initialize", "params": {"capabilities": {}}},
                {"method": "textDocument/didOpen", "params": {"textDocument": {"uri": uri, "text": self.MAIN}}},
                {"id": 2, "method": "textDocument/hover", "params": at(10, 9)},
                {"id": 3, "method": "textDocument/definition", "params": at(8, 11)},
                {"id": 4, "method": "textDocument/references", "params": at(4, 28)},
                {"id": 5, "method": "textDocument/rename", "params": dict(at(8, 6), newName="circle")},
                {"id": 6, "method": "textDocument/documentSymbol", "params": doc},
                {"id": 7, "method": "textDocument/completion", "params": at(11, 14)},
                {"id": 8, "method": "textDocument/signatureHelp", "params": at(9, 27)},
                {"id": 9, "method": "textDocument/formatting", "params": doc},
                {"id": 10, "method": "shutdown"},
                {"method": "exit"},
            ])
            self.assertIn("hoverProvider", res[1]["capabilities"])
            diags = notes[0]["params"]["diagnostics"]
            self.assertEqual([x["code"] for x in diags], ["E0606"])
            self.assertEqual(diags[0]["data"]["edits"][0]["newText"], "pub ")      # fix lands in geo.klar
            self.assertTrue(diags[0]["data"]["edits"][0]["uri"].endswith("geo.klar"))
            self.assertIn("fn total[T: Shape]", res[2]["contents"]["value"])
            self.assertIn("Sum of areas", res[2]["contents"]["value"])
            self.assertTrue(res[3]["uri"].endswith("geo.klar"))
            self.assertEqual(res[3]["range"]["start"]["line"], 12)               # `pub fn unit`
            self.assertEqual(len(res[4]), 3)                                        # trait, impl, call
            self.assertEqual([e["range"]["start"]["line"] for e in res[5]["changes"][uri]], [8, 10])
            self.assertEqual([s["name"] for s in res[6]], ["total", "main"])
            labels = [i["label"] for i in res[7]["items"]]
            self.assertIn("len", labels)
            self.assertIn("sep: Str", res[8]["signatures"][0]["label"])
            self.assertEqual(res[9], [])                                            # already formatted

    def test_bad_input_never_kills_the_server(self):
        uri = "file:///tmp/klar_lsp_broken.klar"
        res, notes = self.session([
            {"method": "textDocument/didOpen", "params": {"textDocument": {"uri": uri, "text": "fn main( {"}}},
            {"id": 1, "method": "textDocument/hover", "params": {"textDocument": {"uri": uri},
                                                                  "position": {"line": 0, "character": 3}}},
            {"id": 2, "method": "textDocument/unknownThing", "params": {}},
            {"id": 3, "method": "textDocument/definition", "params": {"textDocument": {"uri": uri}}},
        ])
        self.assertEqual(notes[0]["params"]["diagnostics"][0]["code"], "E0003")
        self.assertIsNone(res[1])
        self.assertEqual(res[2]["code"], -32601)
        self.assertIsNone(res[3])


class Repl(unittest.TestCase):
    def session(self, text, cwd=None):
        from klar.tools.repl import Repl as R
        out = io.StringIO()
        R(cwd=cwd, out=out, inp=io.StringIO(text)).loop()
        return out.getvalue()

    def test_values_types_and_state(self):
        out = self.session('let xs = [3, 1, 2]\nxs.sort()\nfn double(n: Int) -> Int {\n  return n * 2\n}\n'
                           'xs.map(double)\nvar total = 0\nfor x in xs {\n  total = total + x\n}\nprint("t={total}")\n'
                           ':type total.to_float()\n')
        self.assertEqual(out, "[1, 2, 3] : List[Int]\ndefined double\n[6, 2, 4] : List[Int]\nt=6\nFloat\n")

    def test_errors_do_not_change_the_session(self):
        out = self.session('let n = 1\nlet n = 2\n"a" + n\nfail("boom")\nn\n:quit\nprint("never")\n')
        self.assertIn("E0102", out)
        self.assertIn("E0211", out)
        self.assertIn("runtime error[R0004]: fail: boom", out)
        self.assertTrue(out.endswith("1 : Int\n"))

    def test_load_and_use(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "lib.klar"), "w", encoding="utf-8") as f:
                f.write("/// Squares.\nfn sq(n: Int) -> Int {\n  return n * n\n}\n\nfn main() uses io {\n  print(1)\n}\n")
            out = self.session(":load lib.klar\nsq(7)\nuse std.math.{gcd}\ngcd(12, 18)\n", cwd=d)
            self.assertEqual(out, "defined sq\n49 : Int\n6 : Int\n")


class Modules(unittest.TestCase):
    def write(self, d, name, text):
        path = os.path.join(d, *name.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def test_import_and_run(self):
        with tempfile.TemporaryDirectory() as d:
            self.write(d, "lib/geo.klar", "pub type P { x: Int }\nfn helper(n: Int) -> Int { return n * 2 }\n"
                                          "pub fn double_x(p: P) -> Int { return helper(p.x) }\npub const K: Int = 7\n")
            main = self.write(d, "main.klar", "use lib.geo.{P, double_x, K}\nuse std.math.{gcd}\n"
                                              "fn main() uses io { print(P { x: 4 }.double_x() + K + gcd(9, 6)) }\n")
            code, out, err = cli("run", main)
            self.assertEqual((code, out), (0, "18\n"), err)

    def test_private_names_need_import(self):
        with tempfile.TemporaryDirectory() as d:
            self.write(d, "a.klar", "type P { x: Int }\npub fn make() -> P { return P { x: 1 } }\n")
            main = self.write(d, "main.klar", "use a.{make}\nfn main() uses io { let p = P { x: 2 }\n print(p.x) }\n")
            loaded = load_path(main)
            self.assertIn("E0104", [x.code for x in loaded.diags])
            # field access on a value of a non-imported type is fine
            main2 = self.write(d, "m2.klar", "use a.{make}\nfn main() uses io { print(make().x) }\n")
            self.assertEqual(cli("run", main2)[1], "1\n")

    def test_only_pub_declarations_are_importable(self):
        with tempfile.TemporaryDirectory() as d:
            self.write(d, "a.klar", "pub fn shown() -> Int {\n  return hidden() + 1\n}\n\nfn hidden() -> Int {\n"
                                    "  return 41\n}\n")
            main = self.write(d, "main.klar", "use a.{shown, hidden}\n\nfn main() uses io {\n"
                                              "  print(shown() + hidden())\n}\n")
            got = [(x.code, x.span.file) for x in load_path(main).diags]
            self.assertIn(("E0606", "main.klar"), got)
            cli("fix", main)                        # the fix adds `pub` in a.klar
            with open(os.path.join(d, "a.klar"), encoding="utf-8") as f:
                self.assertIn("pub fn hidden", f.read())
            self.assertEqual(cli("run", "--interp", main)[1], "83\n")

    def test_unused_private_function_warns(self):
        got = codes("fn helper() -> Int {\n  return 1\n}\n\nfn main() uses io {\n  print(2)\n}\n")
        self.assertIn("W0406", got)
        self.assertNotIn("W0406", codes("fn helper() -> Int {\n  return 1\n}\n\ntest \"h\" {\n"
                                        "  assert helper() == 1\n}\n"))

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


def write_tree(root, files):
    for name, text in files.items():
        path = os.path.join(root, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)


def git_available():
    import shutil
    return shutil.which("git") is not None


class Packages(unittest.TestCase):
    """klar.toml, dependencies in `use`, and klar add / fetch / update / remove / deps."""

    GEO = {"klar.toml": "[package]\nname = \"geo\"\n",
           "lib.klar": "use shapes.{Circle, area}\n\npub fn unit_area() -> Float {\n  return area(Circle { r: 1.0 })\n}\n",
           "shapes.klar": "pub type Circle { r: Float }\n\npub fn area(c: Circle) -> Float {\n  return 3.0 * c.r * c.r\n}\n"}

    def test_path_dependencies_and_module_names(self):
        with tempfile.TemporaryDirectory() as d:
            write_tree(os.path.join(d, "geo"), self.GEO)
            write_tree(os.path.join(d, "app"), {
                "klar.toml": "[package]\nname = \"app\"\n\n[dependencies]\ngeo = { path = \"../geo\" }\n",
                "main.klar": "use geo.{unit_area}\nuse geo.shapes.{Circle, area}\nuse shapes.{double}\n\n"
                             "fn main() uses io {\n  print(unit_area() + area(Circle { r: 2.0 }) + double(1.0))\n}\n",
                "shapes.klar": "pub fn double(x: Float) -> Float {\n  return x * 2.0\n}\n"})
            main = os.path.join(d, "app", "main.klar")
            lp = load_path(main)
            self.assertEqual([x.code for x in lp.diags if x.severity == "error"], [])
            # the project's `shapes` and geo's `shapes` are different modules
            self.assertEqual(sorted(m.name for m in lp.modules if m.name not in ("prelude",)),
                             ["geo", "geo.shapes", "main", "shapes"])
            self.assertEqual(cli("run", "--interp", main)[1], "17.0\n")
            self.assertEqual(cli("run", main)[1], "17.0\n")

    def test_package_errors(self):
        with tempfile.TemporaryDirectory() as d:
            write_tree(d, {"klar.toml": "[dependencies]\ngeo = { path = \"geo\" }\nnet = { git = \"https://x/n.git\" }\n",
                           "geo.klar": "pub fn f() -> Int {\n  return 1\n}\n", "geo/klar.toml": "",
                           "main.klar": "use geo.{f}\nuse net.{g}\n\nfn main() uses io {\n  print(1)\n}\n"})
            codes = [x.code for x in load_path(os.path.join(d, "main.klar")).diags]
            self.assertIn("E0607", codes)
            self.assertIn("E0609", codes)
            write_tree(d, {"klar.toml": "[dependencies]\ngeo = { path = \"geo\", tag = \"v1\" }\n"})
            ds = [x for x in load_path(os.path.join(d, "main.klar")).diags if x.code == "E0610"]
            self.assertEqual((ds[0].span.file, ds[0].span.line), ("klar.toml", 2))

    @unittest.skipUnless(git_available(), "needs git")
    def test_git_values_cannot_become_options(self):
        """A klar.toml or klar.lock value that starts with `-` would be read by git as an option: refused."""
        with tempfile.TemporaryDirectory() as d:
            for toml in ('[dependencies]\nx = { git = "--upload-pack=touch PWNED" }\n',
                         '[dependencies]\nx = { git = "https://example.invalid/x.git", rev = "--output=PWNED" }\n'):
                write_tree(d, {"klar.toml": "[package]\nname = \"app\"\n\n" + toml})
                code, out, err = cli("fetch", "--dir", d)
                self.assertNotEqual(code, 0)
                self.assertIn("starts with `-`", out + err)
                self.assertFalse(os.path.exists(os.path.join(d, "PWNED")))

    @unittest.skipUnless(git_available(), "needs git")
    def test_git_dependencies_lock_and_update(self):
        import subprocess

        def git(*a, cwd):
            subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *a], cwd=cwd, check=True,
                           capture_output=True)
        with tempfile.TemporaryDirectory() as d:
            lib = os.path.join(d, "greeter")
            write_tree(lib, {"klar.toml": "[package]\nname = \"greeter\"\n",
                             "lib.klar": "pub fn greet() -> Str {\n  return \"v1\"\n}\n"})
            git("init", "-q", "-b", "main", cwd=lib)
            git("add", "-A", cwd=lib)
            git("commit", "-qm", "1", cwd=lib)
            app = os.path.join(d, "app")
            self.assertEqual(cli("new", app)[0], 0)
            with open(os.path.join(app, "main.klar"), "w", encoding="utf-8") as f:
                f.write("use greeter.{greet}\n\nfn main() uses io {\n  print(greet())\n}\n")
            import pathlib
            url = pathlib.Path(lib).as_uri()
            self.assertEqual(cli("add", "greeter", "--git", url, "--branch", "main", "--dir", app)[0], 0)
            main = os.path.join(app, "main.klar")
            self.assertEqual(cli("run", "--interp", main)[1], "v1\n")
            with open(os.path.join(app, "klar.lock"), encoding="utf-8") as f:
                self.assertIn('ref = "branch main"', f.read())
            # a new upstream commit: fetch keeps the locked one, update moves to it
            with open(os.path.join(lib, "lib.klar"), "w", encoding="utf-8") as f:
                f.write("pub fn greet() -> Str {\n  return \"v2\"\n}\n")
            git("commit", "-qam", "2", cwd=lib)
            self.assertEqual(cli("fetch", "--dir", app)[0], 0)
            self.assertEqual(cli("run", "--interp", main)[1], "v1\n")
            self.assertEqual(cli("update", "--dir", app)[0], 0)
            self.assertEqual(cli("run", "--interp", main)[1], "v2\n")
            code, out, _ = cli("deps", "--json", "--dir", app)
            self.assertEqual(json.loads(out)["deps"][0]["name"], "greeter")
            self.assertEqual(cli("remove", "greeter", "--dir", app)[0], 0)
            self.assertFalse(os.path.exists(os.path.join(app, "klar.lock")))
            with open(os.path.join(app, "klar.toml"), encoding="utf-8") as f:
                self.assertNotIn("greeter", f.read())


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


    def write(self, d, src):
        path = os.path.join(d, "p.klar")
        with open(path, "w", encoding="utf-8") as f:
            f.write(src)
        return path

    def test_profile_exit_is_a_normal_end(self):
        with tempfile.TemporaryDirectory() as d:
            path = self.write(d, "fn main() uses io {\n  print(1)\n  exit(3)\n}\n")
            code, out, _ = cli("profile", "--json", path)
        self.assertEqual(code, 3)
        self.assertTrue(json.loads(out)["ok"])

    def test_profile_names_lambdas_after_the_calling_line(self):
        with tempfile.TemporaryDirectory() as d:
            path = self.write(d, "fn main() uses io {\n  let xs = [1, 2, 3]\n    .map(fn(x) => x + 1)\n"
                                 "  print(xs)\n}\n")
            _, out, _ = cli("profile", "--json", path)
        calls = {f["function"]: f["calls"] for f in json.loads(out)["functions"]}
        self.assertEqual(calls.get("<lambda> (p.klar:2)"), 3)

    def test_profile_reports_check_errors_as_json(self):
        with tempfile.TemporaryDirectory() as d:
            path = self.write(d, "fn main() uses io {\n  print(x)\n}\n")
            code, out, _ = cli("profile", "--json", path)
        data = json.loads(out)
        self.assertEqual((code, data["ok"], data["stage"]), (1, False, "check"))
        self.assertEqual(data["diagnostics"][0]["code"], "E0201")


class NativeTargets(unittest.TestCase):
    """The executables for the targets this machine cannot run: their format, and runs under emulators."""

    def build(self, d, src, target, tests=None):
        from klar.native.build import build
        path = os.path.join(d, "p.klar")
        with open(path, "w", encoding="utf-8") as f:
            f.write(src)
        out = os.path.join(d, "p." + target)
        build(path, out=out, target=target, tests=tests)
        with open(out, "rb") as f:
            return out, f.read()

    def test_macos_executable_is_a_static_mach_o(self):
        import struct
        with tempfile.TemporaryDirectory() as d:
            _, data = self.build(d, "fn main() uses io {\n  print(\"hi\")\n}\n", "macos")
        magic, cpu, _, ftype, ncmds, size, flags, _ = struct.unpack_from("<IiiIIIII", data, 0)
        self.assertEqual((magic, cpu, ftype, flags), (0xFEEDFACF, 0x01000007, 2, 1))
        off, cmds, entry, segments = 32, [], None, {}
        for _ in range(ncmds):
            cmd, csize = struct.unpack_from("<II", data, off)
            cmds.append(cmd)
            if cmd == 0x19:
                name, vmaddr, vmsize = struct.unpack_from("<16sQQ", data, off + 8)
                segments[name.rstrip(b"\0").decode()] = (vmaddr, vmsize)
            if cmd == 0x5:
                entry = struct.unpack_from("<21Q", data, off + 16)[16]
            off += csize
        self.assertEqual(off, 32 + size)
        self.assertNotIn(0xE, cmds)                       # no LC_LOAD_DYLINKER: static, no dyld
        self.assertEqual(segments["__PAGEZERO"], (0, 1 << 32))
        text = segments["__TEXT"]
        self.assertTrue(text[0] < entry < text[0] + text[1])

    def test_macos_executable_runs_under_the_emulator(self):
        try:
            import unicorn  # noqa: F401
        except ImportError:
            self.skipTest("needs the unicorn module")
        src = ("fn main() uses io, fs {\n  print(cli_args())\n  print([1, 2, 3].par_map(fn(x) => x * x))\n"
               "  print(list_dir(\".\").is_ok())\n  print(read_line())\n  exit(4)\n}\n")
        with tempfile.TemporaryDirectory() as d:
            exe, _ = self.build(d, src, "macos")
            p = subprocess.run([sys.executable, os.path.join(ROOT, "tests", "macho_run.py"), exe, "a"],
                               input="line\n", capture_output=True, text=True, cwd=d)
        self.assertEqual((p.stdout, p.returncode), ('["a"]\n[1, 4, 9]\ntrue\nSome("line")\n', 4))

    def test_windows_run_capture(self):
        wine = "/usr/lib/wine/wine64"
        if not os.path.exists(wine):
            self.skipTest("needs wine")
        src = ('fn main() uses io, proc {\n'
               '  print(run_capture(args: ["cmd", "/c", "echo hello"], dir: "", input: ""))\n'
               '  print(run_capture(args: ["cmd", "/c", "echo oops 1>&2 & exit 3"], dir: "", input: ""))\n'
               '  print(run_capture(args: ["findstr", "x"], dir: "", input: "ax\\nb\\n"))\n'
               '  print(run_capture(args: ["klar-surely-missing-42"], dir: "", input: ""))\n}\n')
        with tempfile.TemporaryDirectory() as d:
            exe, _ = self.build(d, src, "windows")
            p = subprocess.run([wine, exe], capture_output=True, env=dict(os.environ, WINEDEBUG="-all"))
        lines = p.stdout.decode().replace("\r", "").split("\n")      # (Windows programs end lines with \r\n)
        self.assertEqual(lines[0], 'Ok(["0", "hello\\n", ""])')
        self.assertTrue(lines[1].startswith('Ok(["3", "", "oops'))
        self.assertTrue(lines[2].startswith('Ok(["0", "ax\\n'))
        self.assertEqual(lines[3], "Err(\"cannot run 'klar-surely-missing-42': No such file or directory\")")

    def test_windows_programs_are_not_taken_from_the_current_directory(self):
        """CreateProcessA would run ./findstr.exe before the one in PATH: the runtime passes the full PATH match."""
        wine = "/usr/lib/wine/wine64"
        if not os.path.exists(wine):
            self.skipTest("needs wine")
        with tempfile.TemporaryDirectory() as d:
            fake, _ = self.build(d, 'fn main() uses io {\n  print("HIJACK")\n}\n', "windows")
            os.rename(fake, os.path.join(d, "findstr.exe"))
            exe, _ = self.build(d, 'fn main() uses io, proc {\n  print(run_capture(args: ["findstr", "x"], dir: "", '
                                   'input: "ax\\n"))\n  print(run_command(["findstr", "zz"]))\n}\n', "windows")
            p = subprocess.run([wine, exe], capture_output=True, cwd=d, env=dict(os.environ, WINEDEBUG="-all"),
                               input=b"")
        self.assertNotIn(b"HIJACK", p.stdout)
        self.assertIn(b'Ok(["0", "ax', p.stdout)

    def test_windows_properties_run_without_fork(self):
        wine = "/usr/lib/wine/wine64"
        if not os.path.exists(wine):
            self.skipTest("needs wine")
        src = ('property "small" (n: Int) {\n  assert n < 50\n}\n\nproperty "fine" (xs: List[Int]) {\n'
               '  assert xs.reverse().reverse() == xs\n}\n')
        loaded = load_source(src, "p.klar")
        tests = [d for d in loaded.program.decls if type(d).__name__ == "PropertyDecl"]
        with tempfile.TemporaryDirectory() as d:
            exe, _ = self.build(d, src, "windows", tests=tests)
            env = dict(os.environ, WINEDEBUG="-all")
            bad = subprocess.run([wine, exe, "100", "0", "0"], capture_output=True, text=True, env=env)
            good = subprocess.run([wine, exe, "100", "0", "1"], capture_output=True, text=True, env=env)
        self.assertEqual(good.returncode, 0, good.stderr)
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("R0010", bad.stderr)
        self.assertIn("n = 50", bad.stderr)                # shrunk to the smallest counterexample


class RuntimeLimits(unittest.TestCase):
    """Sizes and depths that would break the machine (heap overflow, stack overflow) end with a Klar runtime error
    in native code and in the interpreter — never with a crash."""

    CASES = [
        ('fn main() uses io {\n  print("AAAAAAAA".repeat(2305843009213693952).len())\n}\n', "R0015"),
        ('fn main() uses io {\n  print(range(0, 2305843009213693952).len())\n}\n', "R0015"),
        ('fn main() uses io {\n  var x = 1.0\n  var i = 0\n  while i < 400 {\n    x = x * 10.0\n    i = i + 1\n  }\n'
         '  print(x.to_int())\n}\n', "R0009"),
        ('enum T {\n  Leaf,\n  Node(t: T),\n}\n\nfn main() uses io {\n  var t = T.Leaf\n  var i = 0\n'
         '  while i < 300000 {\n    t = T.Node(t: t)\n    i = i + 1\n  }\n  print(t.to_str().len())\n}\n', "R0006"),
        ('enum T {\n  Leaf,\n  Node(t: T),\n}\n\nfn main() uses io {\n  var a = T.Leaf\n  var b = T.Leaf\n'
         '  var i = 0\n  while i < 300000 {\n    a = T.Node(t: a)\n    b = T.Node(t: b)\n    i = i + 1\n  }\n'
         '  print(a == b)\n}\n', "R0006"),
    ]

    def test_native_and_interpreter(self):
        from klar.native.build import build, host_target
        for src, code in self.CASES:
            with tempfile.TemporaryDirectory() as d:
                path = os.path.join(d, "p.klar")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(src)
                _, _, err = cli("run", "--interp", path)
                self.assertIn(f"runtime error[{code}]", err, src)
                if host_target() == "linux":
                    exe = os.path.join(d, "p")
                    build(path, out=exe, target="linux")
                    p = subprocess.run([exe], capture_output=True, text=True)
                    self.assertEqual(p.returncode, 1, src + p.stderr)
                    self.assertIn(f"runtime error[{code}]", p.stderr, src)

    def test_deeply_nested_source_is_a_diagnostic(self):
        src = "fn main() uses io {\n  print(" + "(" * 40000 + "1" + ")" * 40000 + ")\n}\n"
        self.assertEqual(errors(src), ["E0003"])
        src = "fn main() uses io {\n  print(" + "(" * 150 + "1" + ")" * 150 + ")\n}\n"
        self.assertEqual(errors(src), [])
        # the limit (200 levels) keeps every later pass far from the stack limits, also on Windows
        src = "fn main() uses io {\n  print(" + "[" * 250 + "1" + "]" * 250 + ")\n}\n"
        self.assertEqual(errors(src), ["E0003"])
        self.assertEqual(errors("fn f(x: " + "List[" * 300 + "Int" + "]" * 300 + ") {\n}"), ["E0003"])


class LlmBenchmark(unittest.TestCase):
    """bench/ai/llm_bench.py: the reference solutions pass every hidden test, and wrong answers are scored as such."""

    def bench(self):
        sys.path.insert(0, os.path.join(ROOT, "bench", "ai"))
        import llm_bench
        with open(llm_bench.TASKS, encoding="utf-8") as f:
            return llm_bench, json.load(f)

    def test_references_pass(self):
        import shutil
        bench, tasks = self.bench()
        langs = ["klar", "python"] + (["typescript"] if shutil.which("tsc") and shutil.which("node") else [])
        for task in tasks:
            for lang in langs:
                if lang == "typescript" and task["id"] > "05":
                    continue                    # (tsc is slow: a few tasks are enough here)
                code = bench.extract_code(bench.reference(task, lang)[0])
                result = bench.evaluate(task, lang, code)
                self.assertTrue(result["ok"], f"{task['id']} {lang}: {result['feedback']}")

    def test_failures_are_classified(self):
        bench, tasks = self.bench()
        rle = next(t for t in tasks if t["id"] == "03_rle")
        wrong = {"klar": "pub fn rle(s: Str) -> Str {\n  return s\n}\n",
                 "python": "def rle(s: str) -> str:\n    return s\n"}
        broken = {"klar": "pub fn rle(s: Str) -> Str {\n  return s.length()\n}\n",
                  "python": "def rle(s: str) -> str\n    return s\n"}
        for lang in ("klar", "python"):
            r = bench.evaluate(rle, lang, wrong[lang])
            self.assertEqual((r["ok"], r["stage"]), (False, "test"), lang)
            self.assertIn("a3b1c2", r["feedback"])
            r = bench.evaluate(rle, lang, broken[lang])
            self.assertEqual((r["ok"], r["stage"]), (False, "compile"), lang)
        self.assertIn("E0204", bench.evaluate(rle, "klar", broken["klar"])["feedback"])
        self.assertEqual(bench.extract_code("text\n```klar\nfn f() {}\n```\nmore"), "fn f() {}\n")


class Mcp(unittest.TestCase):
    """`klar mcp`: the Model Context Protocol server (klarc mcp gives the same answers: tests/selfhost.py)."""

    def session(self, msgs):
        from klar.tools.mcp import serve
        out = io.StringIO()
        serve(io.StringIO("\n".join(m if isinstance(m, str) else json.dumps(m) for m in msgs) + "\n"), out)
        return [json.loads(line) for line in out.getvalue().splitlines()]

    def test_protocol(self):
        got = self.session([{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "x"}},
                            {"jsonrpc": "2.0", "method": "notifications/initialized"},
                            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                            {"jsonrpc": "2.0", "id": 3, "method": "nope"}, "not json"])
        self.assertEqual(len(got), 4)                     # no answer to the notification
        self.assertEqual(got[0]["result"]["protocolVersion"], "x")
        self.assertIn("tools", got[0]["result"]["capabilities"])
        names = [t["name"] for t in got[1]["result"]["tools"]]
        for name in ("klar_check", "klar_dev", "klar_test", "klar_eval", "klar_doc", "klar_patch", "klar_spec"):
            self.assertIn(name, names)
        for t in got[1]["result"]["tools"]:
            self.assertEqual(t["inputSchema"]["type"], "object")
            self.assertTrue(set(t["inputSchema"]["required"]) <= set(t["inputSchema"]["properties"]))
        self.assertEqual(got[2]["error"]["code"], -32601)
        self.assertEqual(got[3]["error"]["code"], -32700)

    def test_tools(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "t.klar")
            with open(path, "w", encoding="utf-8") as f:
                f.write("fn double(x: Int) -> Int {\n  return x * 2\n}\n\n"
                        "test \"double\" {\n  assert double(2) == 4\n}\n\nfn main() uses io {\n  print(double(21))\n}\n")

            def call(i, tool, **args):
                return {"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": tool, "arguments": args}}
            got = self.session([call(1, "klar_dev", file=path), call(2, "klar_eval", expression="double(5)", file=path),
                                call(3, "klar_check", file=os.path.join(d, "missing.klar")), call(4, "klar_check"),
                                call(5, "nope")])
        dev = json.loads(got[0]["result"]["content"][0]["text"])
        self.assertEqual((dev["ok"], dev["tests"]["passed"], dev["run"]["stdout"]), (True, 1, "42\n"))
        self.assertFalse(got[0]["result"]["isError"])
        self.assertEqual(json.loads(got[1]["result"]["content"][0]["text"])["value"], "10")
        self.assertTrue(got[2]["result"]["isError"])
        self.assertEqual(got[3]["result"]["content"][0]["text"], "missing argument: file")
        self.assertEqual(got[4]["error"]["code"], -32602)


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

    def test_exit_ends_a_path(self):
        self.assertEqual(errors("fn f(n: Int) -> Int uses io {\n if n > 0 {\n return n\n }\n exit(3)\n}"), [])
        self.assertEqual(runtime_code("fn f(n: Int) -> Int uses io {\n if n > 0 {\n return n\n }\n exit(3)\n}\n"
                                      "fn main() uses io { print(f(0)) }"), "R0013")

    def test_values_with_functions_cannot_be_compared(self):
        self.check_code("fn main() uses io {\n let f = fn(x: Int) => x\n print(Some(f) == Some(f))\n}", "E0211")
        self.check_code("type H { f: fn(Int) -> Int }\nfn main() uses io {\n let h = H { f: fn(x) => x }\n"
                        " print(h == h)\n}", "E0211")
        self.check_code("fn main() uses io {\n let f = fn(x: Int) => x\n print([f] != [f])\n}", "E0211")
        self.assertEqual(errors("type P { x: Int }\nfn main() uses io { print(P { x: 1 } == P { x: 1 }) }"), [])

    def test_map_keys_are_values_without_functions(self):
        out = run("""
type P { x: Int, s: Str }
fn main() uses io {
  let m = Map { P { x: 1, s: "a" }: 3, P { x: 2, s: "b" }: 4 }
  print(m.get(P { x: 1, s: "a" }))
  let f = Map { 1.5: "x", -0.0: "z" }.set(0.0, "y")
  print(f)
  print(Map { [1, 2]: 1 }.set([1, 2], 2))
  print(Map { 1: 2, 3: 4 } == Map { 3: 4, 1: 2 })
}""")
        self.assertEqual(out, 'Some(3)\nMap { 1.5: "x", -0.0: "y" }\nMap { [1, 2]: 2 }\ntrue\n')
        self.check_code("fn tw(x: Int) -> Int {\n return x\n}\nfn main() uses io { print(Map { [tw]: 1 }.len()) }",
                        "E0202")

    def test_property_inputs_cannot_break_newtype_invariants(self):
        self.check_code("type Pct = new Int\n  requires value >= 0\nproperty \"p\" (p: Pct) {\n assert p.value >= 0\n}",
                        "E0605")
        self.check_code("type W = new Int\n  requires value >= 0\ntype Box { w: W }\n"
                        "property \"p\" (b: List[Box]) {\n assert b.len() >= 0\n}", "E0605")
        self.assertEqual(errors("type Id = new Int\nproperty \"p\" (i: Id) {\n assert i == i\n}"), [])

    def test_lexer_digits_are_ascii(self):
        self.check_code("fn main() uses io { print(\u0663) }", "E0001")      # Arabic-Indic three
        self.check_code("fn main() uses io { print(2\u00b2) }", "E0001")     # superscript two (crashed the lexer)

    def test_non_ascii_names_warn_with_a_useful_hint(self):
        ds = [d for d in diags("fn main() uses io {\n let \u0438\u043c\u044f = 1\n print(\u0438\u043c\u044f)\n}")
              if d.code == "W0104"]
        self.assertEqual(len(ds), 1)
        self.assertIn("ASCII", ds[0].hint)

    def test_loops(self):
        self.check_code("fn f() { break }", "E0213")
        self.check_code("fn f(m: Map[Str, Int]) { for k in m { } }", "E0202")

    def test_main_signature(self):
        self.check_code("fn main(x: Int) { }", "E0502")


if __name__ == "__main__":
    unittest.main()
