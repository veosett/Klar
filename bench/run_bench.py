#!/usr/bin/env python3
"""Klar benchmark runner: the same algorithms in Klar (native / Python backend / interpreter), Python, JavaScript, C, C++, Java, Go and Rust.

    python bench/run_bench.py                 # all benchmarks, all languages found on this machine
    python bench/run_bench.py -b fib loop     # selected benchmarks
    python bench/run_bench.py -l klar python  # selected languages
    python bench/run_bench.py --repeat 5

Each program measures its own compute time (printed as `time_ms=`), so process start-up,
JIT/JVM boot and Klar's parse+type-check are excluded from the main number; the full
wall-clock time is reported separately. Results of all languages are cross-checked.
Writes bench/results/<host>.md and .json.
"""
import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PROGRAMS = os.path.join(HERE, "programs")
EXE = ".exe" if os.name == "nt" else ""


def version(cmd):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        text = [l for l in (out.stdout + "\n" + out.stderr).strip().splitlines()
                if l.strip() and not l.startswith("Picked up")]
        return text[0] if text else "?"
    except (OSError, subprocess.TimeoutExpired):
        return None


def detect():
    py = sys.executable
    langs = {}
    pyv = platform.python_implementation() + " " + platform.python_version()
    langs["klar"] = {"ext": "klar", "build": lambda src, exe: [py, "-m", "klar", "build", "-q", src, "-o", exe],
                     "run": lambda src, exe: [exe],
                     "version": "Klar 0.3, native compiler (own x86-64 codegen + linker, no libc)"}
    langs["klar-py"] = {"ext": "klar", "run": lambda src, exe: [py, "-m", "klar", "run", "-q", "--py", src],
                        "version": f"Klar 0.3, Python-bytecode backend (on {pyv})"}
    langs["klar-interp"] = {"ext": "klar", "run": lambda src, exe: [py, "-m", "klar", "run", "-q", "--interp", src],
                            "version": f"Klar 0.3, tree-walking interpreter (on {pyv})"}
    langs["python"] = {"ext": "py", "run": lambda src, exe: [py, src],
                       "version": platform.python_implementation() + " " + platform.python_version()}
    if shutil.which("node"):
        langs["javascript"] = {"ext": "js", "run": lambda src, exe: ["node", src],
                               "version": "Node.js " + (version(["node", "--version"]) or "")}
    cc = shutil.which("gcc") or shutil.which("clang") or shutil.which("cc")
    if cc:
        langs["c"] = {"ext": "c", "build": lambda src, exe: [cc, "-O2", "-o", exe, src],
                      "run": lambda src, exe: [exe], "version": (version([cc, "--version"]) or cc) + " -O2"}
    cxx = shutil.which("g++") or shutil.which("clang++")
    if cxx:
        langs["cpp"] = {"ext": "cpp", "build": lambda src, exe: [cxx, "-O2", "-std=c++17", "-o", exe, src],
                        "run": lambda src, exe: [exe], "version": (version([cxx, "--version"]) or cxx) + " -O2"}
    if shutil.which("java"):
        jv = version(["java", "-version"])
        langs["java"] = {"ext": "java", "run": lambda src, exe: ["java", src], "version": jv or "java"}
    if shutil.which("go"):
        langs["go"] = {"ext": "go", "build": lambda src, exe: ["go", "build", "-o", exe, src],
                       "run": lambda src, exe: [exe], "version": version(["go", "version"])}
    rustc = shutil.which("rustc") or next((p for p in (os.path.expanduser("~/.cargo/bin/rustc"),
                                                         os.path.expanduser("~/.cargo/bin/rustc.exe"))
                                           if os.path.exists(p)), None)
    if rustc:
        langs["rust"] = {"ext": "rs", "build": lambda src, exe: [rustc, "-O", "-o", exe, src],
                         "run": lambda src, exe: [exe], "version": (version([rustc, "--version"]) or "") + " -O"}
    return langs


def parse_output(text):
    result, ms = None, None
    for line in text.splitlines():
        if line.startswith("result="):
            result = line[len("result="):].strip()
        elif line.startswith("time_ms="):
            ms = float(line[len("time_ms="):])
    return result, ms


def run_one(lang, cfg, bench, src, workdir, repeat, timeout):
    exe = os.path.join(workdir, f"{bench}_{lang}{EXE}")
    env = dict(os.environ, PYTHONPATH=ROOT + os.pathsep + os.environ.get("PYTHONPATH", ""),
               JAVA_TOOL_OPTIONS="")
    if "build" in cfg:
        b = subprocess.run(cfg["build"](src, exe), capture_output=True, text=True, env=env, cwd=workdir)
        if b.returncode != 0:
            return {"error": "build failed: " + (b.stderr or b.stdout)[-300:]}
    best, wall_best, result = None, None, None
    for _ in range(repeat):
        t0 = time.perf_counter()
        try:
            p = subprocess.run(cfg["run"](src, exe), capture_output=True, text=True, env=env, cwd=ROOT,
                               timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"error": f"timeout after {timeout}s"}
        wall = (time.perf_counter() - t0) * 1000
        if p.returncode != 0:
            return {"error": (p.stderr or p.stdout)[-300:]}
        result, ms = parse_output(p.stdout)
        if ms is None:
            return {"error": "no time_ms in output"}
        best = ms if best is None else min(best, ms)
        wall_best = wall if wall_best is None else min(wall_best, wall)
    return {"result": result, "compute_ms": best, "wall_ms": wall_best}


def fmt_ms(ms):
    if ms is None:
        return "—"
    if ms < 1:
        return f"{ms:.3f}"
    if ms < 100:
        return f"{ms:.1f}"
    return f"{ms:,.0f}".replace(",", " ")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-b", "--bench", nargs="*", help="benchmarks to run")
    ap.add_argument("-l", "--lang", nargs="*", help="languages to run")
    ap.add_argument("--repeat", type=int, default=3, help="runs per program; the best is reported (default 3)")
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--out", default=os.path.join(HERE, "results"))
    ap.add_argument("--name", help="report file name (default: host name)")
    args = ap.parse_args()

    langs = detect()
    if args.lang:
        langs = {k: v for k, v in langs.items() if k in args.lang}
    benches = sorted(d for d in os.listdir(PROGRAMS) if os.path.isdir(os.path.join(PROGRAMS, d)))
    if args.bench:
        benches = [b for b in benches if b in args.bench]

    print(f"Machine: {platform.node()} | {platform.system()} {platform.machine()} | {platform.processor() or ''}")
    for k, v in langs.items():
        print(f"  {k:<11} {v['version']}")
    print()

    results = {}
    with tempfile.TemporaryDirectory() as workdir:
        for bench in benches:
            results[bench] = {}
            for lang, cfg in langs.items():
                src = os.path.join(PROGRAMS, bench, f"{bench}.{cfg['ext']}")
                if not os.path.exists(src):
                    continue
                print(f"  {bench:<12} {lang:<11} ... ", end="", flush=True)
                r = run_one(lang, cfg, bench, src, workdir, args.repeat, args.timeout)
                results[bench][lang] = r
                print(r.get("error") or f"{fmt_ms(r['compute_ms'])} ms (wall {fmt_ms(r['wall_ms'])} ms)")

    # cross-check results
    mismatches = []
    for bench, rs in results.items():
        values = {lang: r["result"] for lang, r in rs.items() if "result" in r}
        if len(set(values.values())) > 1:
            mismatches.append(f"{bench}: " + ", ".join(f"{k}={v}" for k, v in values.items()))

    order = [l for l in ("c", "cpp", "rust", "go", "java", "javascript", "python", "klar", "klar-py", "klar-interp")
             if l in langs]
    lines = ["# Klar benchmarks", "",
             f"Machine: `{platform.system()} {platform.machine()}`, {os.cpu_count()} CPU, "
             f"{platform.processor() or platform.machine()}. Best of {args.repeat} runs. "
             f"Compute time in milliseconds (measured inside each program, start-up excluded).", "",
             "| benchmark | " + " | ".join(order) + " | Klar speed-up vs Python | Klar time ÷ C |",
             "|---|" + "---:|" * (len(order) + 2)]
    for bench, rs in results.items():
        row = [bench]
        for lang in order:
            r = rs.get(lang, {})
            row.append(fmt_ms(r.get("compute_ms")) if "compute_ms" in r else ("error" if r else "—"))
        k = rs.get("klar", {}).get("compute_ms")
        p = rs.get("python", {}).get("compute_ms")
        c = rs.get("c", {}).get("compute_ms")
        row.append((f"{p / k:.1f}×" if p >= k else f"{p / k:.2f}× (slower)") if k and p else "—")
        row.append(f"{k / max(c, 0.001):.1f}×" if k and c else "—")
        lines.append("| " + " | ".join(row) + " |")
    lines += ["", "Wall-clock time including process start-up (ms):", "",
              "| benchmark | " + " | ".join(order) + " |", "|---|" + "---:|" * len(order)]
    for bench, rs in results.items():
        lines.append("| " + " | ".join([bench] + [fmt_ms(rs.get(l, {}).get("wall_ms")) for l in order]) + " |")
    lines += ["", "Versions:", ""] + [f"- **{k}**: {v['version']}" for k, v in langs.items()]
    lines += ["", "Result check: " + ("all languages produced identical results ✅" if not mismatches
                                      else "MISMATCH ❌ " + "; ".join(mismatches))]
    report = "\n".join(lines)
    print()
    print(report)
    os.makedirs(args.out, exist_ok=True)
    host = args.name or (platform.node() or "host").split(".")[0]
    with open(os.path.join(args.out, f"{host}.md"), "w", encoding="utf-8") as f:
        f.write(report + "\n")
    with open(os.path.join(args.out, f"{host}.json"), "w", encoding="utf-8") as f:
        json.dump({"machine": platform.platform(), "repeat": args.repeat,
                   "versions": {k: v["version"] for k, v in langs.items()}, "results": results}, f, indent=2)
    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
