"""Bootstrap check (self-hosting, stage 5): the Klar compiler written in Klar builds itself.

    stage 1  klar build compiler/klarc.klar          (the Python compiler)      -> klarc1
    stage 2  klarc1 build compiler/klarc.klar        (Klar compiled by Python)  -> klarc2
    stage 3  klarc2 build compiler/klarc.klar        (Klar compiled by Klar)    -> klarc3

All three must be the same bytes, the Windows build of klarc made by klarc2 must equal the one made by `klar build`,
and klarc3 must build and run working programs (also a project with a dependency), run test blocks and report
errors like `klar check`. The arm64 build of klarc made by klarc2 must equal the one made by `klar build`; with
qemu-aarch64 installed it also runs: the arm64 compiler builds the same program bytes as klarc3. Linux x86-64 only
(it runs the binaries).

    python tests/bootstrap.py
"""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

KLARC = os.path.join("compiler", "klarc.klar")
LIB = os.path.join(ROOT, "klar")


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", cwd=ROOT, **kw)


def read(path):
    with open(path, "rb") as f:
        return f.read()


def klarc(exe, args):
    proc = run([exe] + args + ["--lib", LIB])
    if proc.returncode != 0:
        print(f"FAIL {os.path.basename(exe)} {' '.join(args)}: exit {proc.returncode}\n{proc.stdout}{proc.stderr}")
    return proc


def main():
    from klar.native.build import build, host_target
    if host_target() != "linux":
        print("bootstrap: skipped (needs Linux x86-64 to run the stages)")
        return 0
    bad = 0
    with tempfile.TemporaryDirectory() as d:
        stage = [os.path.join(d, f"klarc{k}") for k in (1, 2, 3)]
        build(KLARC, out=stage[0], target="linux")
        for k in (1, 2):
            if klarc(stage[k - 1], ["build", KLARC, "-o", stage[k]]).returncode != 0:
                return 1
            os.chmod(stage[k], 0o755)
        images = [read(p) for p in stage]
        for k in (1, 2):
            if images[k] != images[0]:
                bad += 1
                j = next((i for i, (x, y) in enumerate(zip(images[0], images[k])) if x != y),
                         min(len(images[0]), len(images[k])))
                print(f"DIFF stage {k + 1} != stage 1 at byte {j:#x}")
        print(f"bootstrap: stage1 == stage2 == stage3: {'yes' if not bad else 'no'} ({len(images[0])} bytes)")
        # the Windows build of the compiler
        win_py, win_k = os.path.join(d, "klarc_py.exe"), os.path.join(d, "klarc_k.exe")
        build(KLARC, out=win_py, target="windows")
        if klarc(stage[1], ["build", KLARC, "--target", "windows", "-o", win_k]).returncode != 0 or \
                read(win_k) != read(win_py):
            bad += 1
            print("DIFF klarc.exe built by klarc2 != klarc.exe built by klar build")
        # the arm64 build of the compiler, and (under qemu) the arm64 compiler at work
        a64_py, a64_k = os.path.join(d, "klarc_py.a64"), os.path.join(d, "klarc_k.a64")
        build(KLARC, out=a64_py, target="linux-arm64")
        if klarc(stage[1], ["build", KLARC, "--target", "linux-arm64", "-o", a64_k]).returncode != 0 or \
                read(a64_k) != read(a64_py):
            bad += 1
            print("DIFF arm64 klarc built by klarc2 != arm64 klarc built by klar build")
        elif shutil.which("qemu-aarch64-static") or shutil.which("qemu-aarch64"):
            qemu = shutil.which("qemu-aarch64-static") or shutil.which("qemu-aarch64")
            src = os.path.join("examples", "shapes.klar")
            out_a, out_x = os.path.join(d, "shapes_a"), os.path.join(d, "shapes_x")
            got = run([qemu, a64_k, "build", src, "-o", out_a, "--lib", LIB])
            if got.returncode != 0 or klarc(stage[2], ["build", src, "-o", out_x]).returncode != 0 or \
                    read(out_a) != read(out_x):
                bad += 1
                print(f"DIFF the arm64 klarc (qemu) built {src} differently: exit {got.returncode} {got.stdout[:300]}")
            else:
                print("bootstrap: the arm64 compiler (qemu) builds the same bytes")
        # klarc3 builds programs that behave like the Python compiler's
        for name in ("hello", "bank", "shapes"):
            src = os.path.join("examples", f"{name}.klar")
            exe = os.path.join(d, name)
            if klarc(stage[2], ["build", src, "-o", exe]).returncode != 0:
                bad += 1
                continue
            os.chmod(exe, 0o755)
            got = run([exe])
            want = run([sys.executable, "-m", "klar", "run", "--interp", src])
            if (got.stdout, got.returncode) != (want.stdout, want.returncode):
                bad += 1
                print(f"DIFF {src}: klarc3's executable printed {got.stdout[:200]!r}, the interpreter "
                      f"{want.stdout[:200]!r}")
        # klarc run / klarc test: build into a temporary file and run it (no Python involved)
        src = os.path.join("examples", "shapes.klar")
        got = run([stage[2], "run", src, "--lib", LIB])
        want = run([sys.executable, "-m", "klar", "run", "--interp", src])
        if (got.stdout, got.returncode) != (want.stdout, want.returncode):
            bad += 1
            print(f"DIFF klarc3 run {src}: {got.stdout[:200]!r} / interpreter {want.stdout[:200]!r}")
        got = run([stage[2], "test", os.path.join("examples", "bank.klar"), "--lib", LIB])
        if got.returncode != 0 or "4 passed, 0 failed" not in got.stdout:
            bad += 1
            print(f"DIFF klarc3 test examples/bank.klar: exit {got.returncode}\n{got.stdout[-500:]}")
        # a project with a dependency (klar.toml)
        proj = os.path.join(d, "proj")
        for rel, text in (("app/klar.toml", '[package]\nname = "app"\n\n[dependencies]\ngeo = { path = "../geo" }\n'),
                          ("app/main.klar", "use geo.{area}\nuse geo.shapes.{Sq}\n\nfn main() uses io {\n"
                                            "  print(area(Sq { side: 3 }))\n}\n"),
                          ("geo/klar.toml", '[package]\nname = "geo"\n'),
                          ("geo/lib.klar", "use shapes.{Sq}\n\npub fn area(s: Sq) -> Int {\n  return s.side * s.side\n}\n"),
                          ("geo/shapes.klar", "pub type Sq { side: Int }\n")):
            os.makedirs(os.path.dirname(os.path.join(proj, rel)), exist_ok=True)
            with open(os.path.join(proj, rel), "w", encoding="utf-8") as f:
                f.write(text)
        got = run([stage[2], "run", os.path.join(proj, "app", "main.klar"), "--lib", LIB])
        if (got.stdout, got.returncode) != ("9\n", 0):
            bad += 1
            print(f"DIFF klarc3 run of a project with a path dependency: {got.stdout[:200]!r} {got.stderr[:200]!r}")
        # and reports errors
        proc = run([stage[2], "check", os.path.join("examples", "mistakes.klar"), "--lib", LIB])
        if proc.returncode != 1 or "error[E" not in proc.stdout:
            bad += 1
            print(f"DIFF klarc3 check examples/mistakes.klar: exit {proc.returncode}\n{proc.stdout[:500]}")
        proc = run([stage[2], "check", KLARC, "--lib", LIB])
        if proc.returncode != 0:
            bad += 1
            print(f"DIFF klarc3 check {KLARC}: exit {proc.returncode}\n{proc.stdout[:500]}")
    print("bootstrap: ok" if not bad else f"bootstrap: {bad} problem(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
