"""Bootstrap check (self-hosting, stage 5): the Klar compiler written in Klar builds itself.

    stage 1  klar build compiler/klarc.klar          (the Python compiler)      -> klarc1
    stage 2  klarc1 build compiler/klarc.klar        (Klar compiled by Python)  -> klarc2
    stage 3  klarc2 build compiler/klarc.klar        (Klar compiled by Klar)    -> klarc3

All three must be the same bytes, the Windows build of klarc made by klarc2 must equal the one made by `klar build`,
and klarc3 must build working programs and report errors like `klar check`. Linux x86-64 only (it runs the binaries).

    python tests/bootstrap.py
"""
import os
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
