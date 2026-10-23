"""`klar run --allow fs:./data,proc:git,time`: the declared effects become rights at run time as well. With
`--allow`, a call outside the rights is runtime error R0016 (printing and reading input — `io` — stay allowed):

* `fs` — every file; `fs:DIR` — files and directories inside DIR (relative to the working directory at the start;
  paths are compared as written, after resolving `.` and `..`, without following symbolic links);
* `proc` — every program; `proc:NAME` — only `run_command([NAME, ...])` / `run_capture([NAME, ...], ...)`;
* `time`, `rand`, `net`.

klar/rt/sandbox.klar implements the same checks (and messages) in native code; the rights are built into the
executable (`klar build --allow ...`).
"""
import os

RIGHTS = ("io", "time", "rand", "net", "fs", "proc")
HINTS = {
    "fs": "add the right to `--allow`: `fs` for every file or `fs:DIR` for one directory",
    "proc": "add the right to `--allow`: `proc` for every program or `proc:NAME` for one",
}


class RightsError(ValueError):
    pass


def parse_allow(spec):
    """The rights of an `--allow` value; RightsError for an unknown one."""
    out = []
    for raw in spec.split(","):
        r = raw.strip()
        if not r:
            continue
        kind, _, arg = r.partition(":")
        if kind not in RIGHTS or (arg and kind not in ("fs", "proc")) or (":" in r and not arg):
            raise RightsError(f"unknown right `{r}` (rights: io, time, rand, net, fs, fs:DIR, proc, proc:NAME)")
        out.append(r)
    return out


def segments(path, cwd):
    """The parts of the absolute form of a path: `\\` is a separator too, `.` and `..` are resolved."""
    p = path.replace("\\", "/")
    if not (p.startswith("/") or (len(p) >= 2 and p[1] == ":")):
        p = cwd.replace("\\", "/") + "/" + p
    out = []
    for s in p.split("/"):
        if s in ("", "."):
            continue
        if s == "..":
            if out:
                out.pop()
            continue
        out.append(s)
    return out


class Sandbox:
    def __init__(self, spec, cwd=None):
        self.rights = parse_allow(spec)
        self.shown = ", ".join(self.rights) if self.rights else "nothing"
        self.cwd = os.getcwd() if cwd is None else cwd
        self.dirs = [segments(r[3:], self.cwd) for r in self.rights if r.startswith("fs:")]
        self.all_fs = "fs" in self.rights
        self.progs = [r[5:] for r in self.rights if r.startswith("proc:")]
        self.all_proc = "proc" in self.rights

    def deny(self, what, right, arg, sp):
        from .builtins import rt_error
        subject = f" for '{arg}'" if arg is not None else ""
        raise rt_error("R0016", f"`{what}` needs `--allow {right}`{subject} (allowed: {self.shown})", sp,
                       hint=HINTS.get(right, f"add `{right}` to `--allow`"))

    def need(self, what, right, sp):
        if right not in self.rights:
            self.deny(what, right, None, sp)

    def need_fs(self, what, path, sp):
        if self.all_fs:
            return
        segs = segments(path, self.cwd)
        if any(segs[:len(d)] == d for d in self.dirs):
            return
        self.deny(what, "fs", path, sp)

    def need_any_fs(self, what, sp):
        if not (self.all_fs or self.dirs):
            self.deny(what, "fs", None, sp)

    def need_proc(self, what, args, sp):
        if self.all_proc:
            return
        prog = args[0] if args else ""
        if prog in self.progs:
            return
        self.deny(what, "proc", prog, sp)
