"""Package commands: `klar add`, `klar remove`, `klar fetch`, `klar update`, `klar deps`.

Dependencies are declared in the project's `klar.toml` (see klar/packages.py). Path dependencies are used where they
are; git dependencies are cloned into `<project>/.klar/deps/<name>` by `klar fetch`, which pins the commit of each in
`klar.lock` (commit that file: a later `klar fetch` checks out the same commits; `klar update` moves them forward).
"""
import json
import os
import re
import subprocess
import sys

from ..packages import (LOCKFILE, MANIFEST, NAME, RESERVED, Dependency, ManifestError, dep_root, find_root,
                        parse_manifest, parse_toml)


class PkgError(Exception):
    pass


def project_root(start):
    root = find_root(start)
    if root is None:
        raise PkgError(f"no {MANIFEST} in {os.path.abspath(start)} or above: run `klar new` or create one with a "
                       "[package] section")
    return root


def load_manifest(root):
    path = os.path.join(root, MANIFEST)
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError as ex:
        raise PkgError(f"cannot read {path}: {ex.strerror}")
    try:
        return parse_manifest(text, root)
    except ManifestError as ex:
        raise PkgError(f"{path}:{ex.line}: {ex.message}")


# ---- the lock file -----------------------------------------------------------------------------------------------
def ref_text(dep):
    return f"{dep.ref_kind} {dep.ref}" if dep.ref else "default branch"


def read_lock(root):
    path = os.path.join(root, LOCKFILE)
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as f:
        try:
            data, _ = parse_toml(f.read())
        except ManifestError as ex:
            raise PkgError(f"{path}:{ex.line}: {ex.message} (delete it and run `klar fetch`)")
    return {k: v for k, v in data.items() if k}


def write_lock(root, entries):
    lines = ["# klar.lock — written by `klar fetch`: the exact commit of every git dependency. Commit this file;",
             "# `klar fetch` checks out these commits, `klar update` moves them forward.", ""]
    for name in sorted(entries):
        e = entries[name]
        lines += [f"[{name}]", f'git = "{e["git"]}"', f'ref = "{e["ref"]}"', f'rev = "{e["rev"]}"', ""]
    path = os.path.join(root, LOCKFILE)
    text = "\n".join(lines).rstrip("\n") + "\n"
    if not entries:
        if os.path.exists(path):
            os.remove(path)
        return
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


# ---- git ---------------------------------------------------------------------------------------------------------
def git(*args, cwd=None):
    try:
        proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    except FileNotFoundError:
        raise PkgError("git is not installed (it is needed for git dependencies)")
    if proc.returncode != 0:
        raise PkgError(f"git {' '.join(args)}: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout.strip()


def no_option(value, what):
    """A value from klar.toml or klar.lock that goes into git's command line must not look like an option."""
    if value.startswith("-"):
        raise PkgError(f"refusing the {what} `{value}`: it starts with `-` (git would read it as an option)")


def checkout(target, dep, rev=None):
    """Clones / updates the git dependency into `target` and checks out `rev` (or its tag/branch/rev); returns the
    commit."""
    if rev is not None:
        want = rev
    elif dep.ref_kind == "tag":
        want = f"refs/tags/{dep.ref}"
    elif dep.ref_kind == "branch":
        want = f"origin/{dep.ref}"
    elif dep.ref_kind == "rev":
        want = dep.ref
    else:
        want = "origin/HEAD"
    no_option(dep.git, "git URL")
    no_option(want, "revision")
    if not os.path.isdir(os.path.join(target, ".git")):
        os.makedirs(os.path.dirname(target), exist_ok=True)
        git("clone", "--quiet", "--", dep.git, target)
    else:
        if git("remote", "get-url", "origin", cwd=target) != dep.git:
            git("remote", "set-url", "origin", dep.git, cwd=target)
        git("fetch", "--quiet", "--tags", "--force", "origin", cwd=target)
    git("checkout", "--quiet", "--detach", want, cwd=target)
    return git("rev-parse", "HEAD", cwd=target)


# ---- fetching ----------------------------------------------------------------------------------------------------
def fetch(root, update=None, log=None):
    """Makes every dependency (transitively) available and writes klar.lock. `update`: None (keep locked commits),
    True (re-resolve all) or a set of names. Returns {"packages": [...], "errors": [...]}."""
    log = log or (lambda msg: None)
    lock = read_lock(root)
    resolved = {}           # name -> (root, Dependency, the manifest that named it first)
    packages, errors, new_lock = [], [], {}
    queue = [(root, load_manifest(root))]
    while queue:
        owner, man = queue.pop(0)
        for name, dep in man.deps.items():
            droot = dep_root(root, owner, dep)
            prev = resolved.get(name)
            if prev is not None:
                if prev[0] != droot or (prev[1].git, prev[1].ref) != (dep.git, dep.ref):
                    errors.append(f"dependency `{name}` is {dep.describe()} in "
                                  f"{os.path.relpath(os.path.join(owner, MANIFEST), root)} but {prev[1].describe()} in "
                                  f"{os.path.relpath(os.path.join(prev[2], MANIFEST), root)}")
                continue
            resolved[name] = (droot, dep, owner)
            entry = {"name": name, "source": dep.describe(), "root": os.path.relpath(droot, root)}
            if dep.git is not None:
                locked = lock.get(name)
                keep = update is not True and not (isinstance(update, set) and name in update) and \
                    locked is not None and locked.get("git") == dep.git and locked.get("ref") == ref_text(dep)
                try:
                    log(f"fetching {name} ({dep.git}, {ref_text(dep)})")
                    commit = checkout(droot, dep, locked["rev"] if keep else None)
                except PkgError as ex:
                    errors.append(f"`{name}`: {ex}")
                    continue
                new_lock[name] = {"git": dep.git, "ref": ref_text(dep), "rev": commit}
                entry["rev"] = commit
            if not os.path.isfile(os.path.join(droot, MANIFEST)):
                errors.append(f"`{name}` ({dep.describe()}) is not a package: {os.path.relpath(droot, root)} has no "
                              f"{MANIFEST}")
                continue
            try:
                queue.append((droot, load_manifest(droot)))
            except PkgError as ex:
                errors.append(str(ex))
            packages.append(entry)
    if not errors:
        write_lock(root, new_lock)
    return {"packages": packages, "errors": errors}


# ---- editing klar.toml -------------------------------------------------------------------------------------------
def quote(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def dep_line(dep):
    if dep.path is not None:
        return f"{dep.name} = {{ path = {quote(dep.path)} }}"
    ref = f", {dep.ref_kind} = {quote(dep.ref)}" if dep.ref else ""
    return f"{dep.name} = {{ git = {quote(dep.git)}{ref} }}"


def set_dependency(root, dep):
    """Adds or replaces `name = ...` in [dependencies] (keeping the rest of the file as it is)."""
    path = os.path.join(root, MANIFEST)
    with open(path, encoding="utf-8") as f:
        lines = f.read().split("\n")
    start = next((i for i, x in enumerate(lines) if x.strip() == "[dependencies]"), None)
    if start is None:
        while lines and not lines[-1].strip():
            lines.pop()
        lines += ["", "[dependencies]", dep_line(dep), ""]
    else:
        end = next((i for i in range(start + 1, len(lines)) if lines[i].strip().startswith("[")), len(lines))
        key = re.compile(rf"^\s*\"?{re.escape(dep.name)}\"?\s*=")
        at = next((i for i in range(start + 1, end) if key.match(lines[i])), None)
        if at is not None:
            lines[at] = dep_line(dep)
        else:
            last = max([i for i in range(start, end) if lines[i].strip()], default=start)
            lines.insert(last + 1, dep_line(dep))
    text = "\n".join(lines)
    parse_manifest(text, root)      # (never write a manifest that does not parse)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def remove_dependency(root, name):
    path = os.path.join(root, MANIFEST)
    with open(path, encoding="utf-8") as f:
        lines = f.read().split("\n")
    key = re.compile(rf"^\s*\"?{re.escape(name)}\"?\s*=")
    section = None
    out, found = [], False
    for x in lines:
        if x.strip().startswith("["):
            section = x.strip()
        if section == "[dependencies]" and key.match(x):
            found = True
            continue
        out.append(x)
    if not found:
        raise PkgError(f"`{name}` is not a dependency in {MANIFEST}")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out))


# ---- the commands ------------------------------------------------------------------------------------------------
def report(result, as_json, root):
    if as_json:
        print(json.dumps({"ok": not result["errors"], "project": root, **result}, ensure_ascii=False,
                         separators=(",", ":")))
    else:
        for p in result["packages"]:
            rev = f" @ {p['rev'][:12]}" if "rev" in p else ""
            print(f"  {p['name']:<16} {p['source']}{rev}")
        for e in result["errors"]:
            print(f"error: {e}", file=sys.stderr)
        if not result["errors"]:
            n = len(result["packages"])
            print(f"{n} dependenc{'y' if n == 1 else 'ies'} ready" + (" (klar.lock written)" if any(
                "rev" in p for p in result["packages"]) else ""))
    return 0 if not result["errors"] else 1


def run(fn):
    try:
        return fn()
    except PkgError as ex:
        print(f"error: {ex}", file=sys.stderr)
        return 1


def cmd_add(args):
    def go():
        root = project_root(args.dir)
        if not NAME.match(args.name) or args.name in RESERVED:
            raise PkgError(f"`{args.name}` is not a valid dependency name (snake_case, not std/rt/prelude)")
        refs = [(k, v) for k, v in (("tag", args.tag), ("rev", args.rev), ("branch", args.branch)) if v]
        if (args.path is None) == (args.git is None):
            raise PkgError("give the source: `--path ../dir` or `--git URL` (with --tag, --rev or --branch)")
        if refs and args.git is None:
            raise PkgError("--tag, --rev and --branch are for git dependencies")
        if len(refs) > 1:
            raise PkgError("give at most one of --tag, --rev and --branch")
        dep = Dependency(args.name, args.path, args.git, refs[0][0] if refs else None, refs[0][1] if refs else None)
        set_dependency(root, dep)
        print(f"added {dep_line(dep)}")
        if args.no_fetch:
            return 0
        return report(fetch(root, update={args.name}, log=lambda m: print(m, file=sys.stderr)), args.json, root)
    return run(go)


def cmd_remove(args):
    def go():
        root = project_root(args.dir)
        remove_dependency(root, args.name)
        print(f"removed `{args.name}` from {MANIFEST}")
        return report(fetch(root), args.json, root)
    return run(go)


def cmd_fetch(args):
    def go():
        root = project_root(args.dir)
        return report(fetch(root, log=lambda m: print(m, file=sys.stderr)), args.json, root)
    return run(go)


def cmd_update(args):
    def go():
        root = project_root(args.dir)
        return report(fetch(root, update=set(args.names) or True, log=lambda m: print(m, file=sys.stderr)),
                      args.json, root)
    return run(go)


def tree(root):
    """The dependency tree as nested dicts (what `klar deps` prints), without fetching anything."""
    seen = set()

    def walk(owner):
        try:
            man = load_manifest(owner)
        except PkgError as ex:
            return [{"error": str(ex)}]
        out = []
        for name, dep in man.deps.items():
            droot = dep_root(root, owner, dep)
            node = {"name": name, "source": dep.describe(), "root": os.path.relpath(droot, root)}
            if not os.path.isfile(os.path.join(droot, MANIFEST)):
                node["missing"] = True
            elif name in seen:
                node["repeated"] = True
            else:
                seen.add(name)
                node["deps"] = walk(droot)
            out.append(node)
        return out
    return walk(root)


def cmd_deps(args):
    def go():
        root = project_root(args.dir)
        nodes = tree(root)
        if args.json:
            print(json.dumps({"project": root, "deps": nodes}, ensure_ascii=False, separators=(",", ":")))
            return 0
        man = load_manifest(root)
        print(f"{man.name or os.path.basename(root)} {man.version or ''}".rstrip())

        def show(ns, indent):
            for n in ns:
                if "error" in n:
                    print(f"{indent}error: {n['error']}")
                    continue
                note = "  (not fetched: run `klar fetch`)" if n.get("missing") else \
                    "  (see above)" if n.get("repeated") else ""
                print(f"{indent}{n['name']}  {n['source']}{note}")
                show(n.get("deps", []), indent + "  ")
        show(nodes, "  ")
        return 0
    return run(go)


def register(sub):
    p = sub.add_parser("add", help="add a dependency to klar.toml and fetch it")
    p.add_argument("name")
    p.add_argument("--path", help="a package directory (relative to klar.toml)")
    p.add_argument("--git", help="a git repository URL")
    p.add_argument("--tag")
    p.add_argument("--rev")
    p.add_argument("--branch")
    p.add_argument("--no-fetch", action="store_true")
    p.add_argument("--dir", default=".", help="the project directory (default: here)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_add)
    p = sub.add_parser("remove", help="remove a dependency from klar.toml")
    p.add_argument("name")
    p.add_argument("--dir", default=".")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_remove)
    p = sub.add_parser("fetch", help="fetch the git dependencies (at the commits in klar.lock) and check all")
    p.add_argument("--dir", default=".")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_fetch)
    p = sub.add_parser("update", help="move git dependencies to the newest commit of their tag/branch")
    p.add_argument("names", nargs="*")
    p.add_argument("--dir", default=".")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_update)
    p = sub.add_parser("deps", help="the dependency tree of the project")
    p.add_argument("--dir", default=".")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_deps)
