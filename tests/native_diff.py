"""Differential testing of the native backend against the reference interpreter.

    python tests/native_diff.py [files...]          (default: examples, std modules, built-in tests, benchmarks)

For programs with main(): stdout and exit status must match.
For test files: every `test` / doc-test block is compiled into one executable
(run as `exe <index>`); pass/fail and the error code must match the interpreter.
Property tests run only in the interpreter (they need the input generator).
"""
import io
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from klar import nodes as N  # noqa: E402
from klar.errors import KlarRuntimeError  # noqa: E402
from klar.interpreter import Interpreter, run_with_big_stack  # noqa: E402
from klar.loader import load_path  # noqa: E402
from klar.native.build import build, host_target  # noqa: E402

TIME_LINE = re.compile(r"^time_ms=.*$", re.M)


def default_files():
    files = [os.path.join(ROOT, "examples", f) for f in ("hello.klar", "bank.klar", "collections.klar",
                                                          "shapes.klar", "features.klar")]
    files += [os.path.join(ROOT, "klar", "std", f) for f in sorted(os.listdir(os.path.join(ROOT, "klar", "std")))]
    files.append(os.path.join(ROOT, "tests", "stdlib", "builtins_test.klar"))
    files.append(os.path.join(ROOT, "tests", "native", "edge_cases.klar"))
    files.append(os.path.join(ROOT, "tests", "native", "bits_and_os.klar"))
    files.append(os.path.join(ROOT, "tests", "native", "traits.klar"))
    files.append(os.path.join(ROOT, "tests", "native", "patterns.klar"))
    files.append(os.path.join(ROOT, "tests", "native", "floats.klar"))
    bench = os.path.join(ROOT, "bench", "programs")
    files += [os.path.join(bench, b, b + ".klar") for b in sorted(os.listdir(bench))]
    return files


def interp_tests(path):
    loaded = load_path(path)
    it = Interpreter(loaded, out=io.StringIO(), err_stream=io.StringIO())
    out = []
    for t in it.tests:
        if isinstance(t, N.PropertyDecl):
            continue
        try:
            run_with_big_stack(lambda: it.run_test(t))
            out.append((t, None))
        except KlarRuntimeError as ex:
            out.append((t, ex.code))
    return out


def run_exe(exe, args=()):
    cmd = [exe, *args]
    if exe.endswith(".exe") and host_target() != "windows":
        cmd = ["/usr/lib/wine/wine64", *cmd]
    env = dict(os.environ, WINEDEBUG="-all")
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env)


def check_file(path, target, tmp):
    loaded = load_path(path, with_runtime=True)
    has_main = any(isinstance(d, N.FnDecl) and d.name == "main" for d in loaded.program.decls)
    problems = []
    suffix = ".exe" if target == "windows" else ""
    if has_main:
        exe = os.path.join(tmp, "main" + suffix)
        build(path, out=exe, target=target, loaded=loaded)
        p = run_exe(exe)
        ref = subprocess.run([sys.executable, "-m", "klar", "run", "-q", "--interp", path], capture_output=True,
                             text=True, cwd=ROOT)
        a, b = TIME_LINE.sub("", ref.stdout), TIME_LINE.sub("", p.stdout)
        if a != b or (ref.returncode == 0) != (p.returncode == 0):
            problems.append(f"main: output/exit differ (interp {ref.returncode}, native {p.returncode})\n"
                            f"--- interp\n{a[-800:]}\n--- native\n{b[-800:]}\n{p.stderr[-800:]}")
    tests = interp_tests(path)
    if tests:
        exe = os.path.join(tmp, "tests" + suffix)
        build(path, out=exe, target=target, loaded=load_path(path, with_runtime=True), tests=[t for t, _ in tests])
        for i, (t, code) in enumerate(tests):
            p = run_exe(exe, [str(i)])
            m = re.search(r"runtime error\[(\w+)\]", p.stderr)
            ncode = None if p.returncode == 0 else (m.group(1) if m else f"exit {p.returncode}")
            if ncode != code:
                problems.append(f"test {t.name!r}: interp={code} native={ncode}\n{p.stderr[-1500:]}")
    return problems, len(tests), has_main


def main(argv):
    target = host_target()
    if "--windows" in argv:
        target = "windows"
        argv = [a for a in argv if a != "--windows"]
    files = argv or default_files()
    failed = 0
    with tempfile.TemporaryDirectory() as tmp:
        for path in files:
            try:
                problems, ntests, has_main = check_file(path, target, tmp)
            except Exception as ex:  # noqa
                problems, ntests, has_main = [f"build failed: {type(ex).__name__}: {ex}"], 0, False
            rel = os.path.relpath(path, ROOT)
            if problems:
                failed += 1
                print(f"FAIL {rel}")
                for pr in problems:
                    print("   " + pr.replace("\n", "\n   "))
            else:
                print(f"ok   {rel}  ({'main, ' if has_main else ''}{ntests} tests)")
    print(f"\n{len(files) - failed}/{len(files)} files agree")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
