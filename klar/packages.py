"""Packages: `klar.toml` manifests and how `use` finds the modules of dependencies.

A project is a directory with a `klar.toml`:

    [package]
    name = "app"
    version = "0.1.0"

    [dependencies]
    geometry = { path = "../geometry" }                                   # a directory with its own klar.toml
    json5 = { git = "https://github.com/someone/json5.git", tag = "v1.2.0" }   # or rev = "<commit>", branch = "main"

`use geometry.{Point}` then loads `<geometry>/lib.klar`, and `use geometry.shapes.{Circle}` loads
`<geometry>/shapes.klar`. Git dependencies live in `<project>/.klar/deps/<name>`, put there by `klar fetch`, which
records the exact commits in `klar.lock`. A dependency name means one package in the whole program; the modules of a
dependency are named after it (`geometry`, `geometry.shapes`), so they never clash with the project's own.

The manifest format is a small subset of TOML (the same subset `compiler/manifest.klar` reads): `[section]` headers,
`key = value` lines, values that are strings, integers, booleans, inline tables `{ k = v, ... }` and arrays of strings,
and `#` comments.
"""
import os
import re

MANIFEST = "klar.toml"
LOCKFILE = "klar.lock"
DEPS_DIR = os.path.join(".klar", "deps")
RESERVED = ("std", "rt", "prelude")
NAME = re.compile(r"^[a-z][a-z0-9_]*$")


class ManifestError(Exception):
    def __init__(self, line, message):
        super().__init__(message)
        self.line = line
        self.message = message


# ---- the TOML subset ---------------------------------------------------------------------------------------------
class _Reader:
    def __init__(self, text, line):
        self.s = text
        self.i = 0
        self.line = line

    def fail(self, msg):
        raise ManifestError(self.line, msg)

    def ws(self):
        while self.i < len(self.s) and self.s[self.i] in " \t":
            self.i += 1

    def peek(self):
        self.ws()
        return self.s[self.i] if self.i < len(self.s) else ""

    def expect(self, ch):
        if self.peek() != ch:
            self.fail(f"expected `{ch}`")
        self.i += 1

    def key(self):
        self.ws()
        if self.peek() == '"':
            return self.string()
        m = re.match(r"[A-Za-z0-9_-]+", self.s[self.i:])
        if not m:
            self.fail("expected a key")
        self.i += m.end()
        return m.group(0)

    def string(self):
        self.expect('"')
        out = []
        while True:
            if self.i >= len(self.s):
                self.fail("unterminated string")
            ch = self.s[self.i]
            self.i += 1
            if ch == '"':
                return "".join(out)
            if ch == "\\":
                if self.i >= len(self.s):
                    self.fail("unterminated string")
                esc = self.s[self.i]
                self.i += 1
                if esc not in 'nt"\\':
                    self.fail(f"unknown escape `\\{esc}`")
                out.append({"n": "\n", "t": "\t"}.get(esc, esc))
            else:
                out.append(ch)

    def value(self):
        ch = self.peek()
        if ch == '"':
            return self.string()
        if ch == "{":
            self.i += 1
            table = {}
            if self.peek() == "}":
                self.i += 1
                return table
            while True:
                k = self.key()
                self.expect("=")
                if k in table:
                    self.fail(f"duplicate key `{k}`")
                table[k] = self.value()
                if self.peek() == ",":
                    self.i += 1
                    continue
                self.expect("}")
                return table
        if ch == "[":
            self.i += 1
            items = []
            if self.peek() == "]":
                self.i += 1
                return items
            while True:
                if self.peek() != '"':
                    self.fail("arrays hold strings")
                items.append(self.string())
                if self.peek() == ",":
                    self.i += 1
                    if self.peek() == "]":
                        self.i += 1
                        return items
                    continue
                self.expect("]")
                return items
        m = re.match(r"-?[0-9]+", self.s[self.i:])
        if m:
            self.i += m.end()
            return int(m.group(0))
        for word, v in (("true", True), ("false", False)):
            if self.s.startswith(word, self.i):
                self.i += len(word)
                return v
        self.fail("expected a value: a string, a number, true/false, `{ ... }` or `[ ... ]`")

    def end(self):
        self.ws()
        if self.i < len(self.s) and self.s[self.i] != "#":
            self.fail("unexpected text after the value")


def parse_toml(text):
    """({section: {key: value}}, {(section, key): line}); keys before the first section go to section "".
    Raises ManifestError."""
    out = {"": {}}
    lines = {}
    section = ""
    for n, raw in enumerate(text.split("\n"), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            m = re.match(r"^\[\s*([A-Za-z0-9_.-]+)\s*\]\s*(#.*)?$", line)
            if not m:
                raise ManifestError(n, "a section header is `[name]`")
            section = m.group(1)
            if section in out:
                raise ManifestError(n, f"duplicate section `[{section}]`")
            out[section] = {}
            lines[(section, "[")] = n
            continue
        r = _Reader(line, n)
        k = r.key()
        r.expect("=")
        v = r.value()
        r.end()
        if k in out[section]:
            raise ManifestError(n, f"duplicate key `{k}`")
        out[section][k] = v
        lines[(section, k)] = n
    return out, lines


# ---- manifests ---------------------------------------------------------------------------------------------------
class Dependency:
    def __init__(self, name, path=None, git=None, ref_kind=None, ref=None, line=0):
        self.name, self.path, self.git, self.ref_kind, self.ref, self.line = name, path, git, ref_kind, ref, line

    def describe(self):
        if self.path is not None:
            return f"path {self.path}"
        return f"git {self.git}" + (f" ({self.ref_kind} {self.ref})" if self.ref else "")


class Manifest:
    def __init__(self, root, name, version, deps):
        self.root = root            # the directory of klar.toml
        self.name = name
        self.version = version
        self.deps = deps            # name -> Dependency (in manifest order)


def parse_manifest(text, root):
    """Raises ManifestError (with a line, 0 when it is not about one line)."""
    data, lines = parse_toml(text)
    for section in data:
        if section not in ("", "package", "dependencies"):
            raise ManifestError(lines[(section, "[")], f"unknown section `[{section}]` "
                                                       "(klar.toml has [package] and [dependencies])")
    for k in data[""]:
        raise ManifestError(lines[("", k)], f"`{k}` must be inside [package] or [dependencies]")
    pkg = data.get("package", {})
    for k in pkg:
        if k not in ("name", "version", "description", "authors", "license"):
            raise ManifestError(lines[("package", k)], f"unknown key `{k}` in [package] "
                                                       "(name, version, description, authors, license)")
    name = pkg.get("name")
    if name is not None and (not isinstance(name, str) or not NAME.match(name)):
        raise ManifestError(lines[("package", "name")], "[package] name must be a snake_case identifier")
    deps = {}
    for dname, spec in data.get("dependencies", {}).items():
        line = lines[("dependencies", dname)]
        if not NAME.match(dname) or dname in RESERVED:
            raise ManifestError(line, f"dependency name `{dname}` must be a snake_case identifier other than "
                                      f"std, rt and prelude (it is the first part of `use {dname}...`)")
        if not isinstance(spec, dict):
            raise ManifestError(line, f"write `{dname} = {{ path = \"...\" }}` or "
                                      f"`{dname} = {{ git = \"...\", tag = \"...\" }}`")
        unknown = [k for k in spec if k not in ("path", "git", "tag", "rev", "branch")]
        if unknown:
            raise ManifestError(line, f"unknown key `{unknown[0]}` for dependency `{dname}` "
                                      "(path, git, tag, rev, branch)")
        if ("path" in spec) == ("git" in spec):
            raise ManifestError(line, f"dependency `{dname}` needs exactly one of `path` and `git`")
        refs = [k for k in ("tag", "rev", "branch") if k in spec]
        if refs and "path" in spec:
            raise ManifestError(line, f"`{refs[0]}` is for git dependencies, `{dname}` has a path")
        if len(refs) > 1:
            raise ManifestError(line, f"dependency `{dname}` names both `{refs[0]}` and `{refs[1]}`: keep one")
        for k, v in spec.items():
            if not isinstance(v, str) or not v:
                raise ManifestError(line, f"`{k}` of dependency `{dname}` must be a non-empty string")
        deps[dname] = Dependency(dname, spec.get("path"), spec.get("git"), refs[0] if refs else None,
                                 spec.get(refs[0]) if refs else None, line)
    return Manifest(root, name, pkg.get("version"), deps)


def find_root(start_dir):
    """The nearest directory at or above start_dir with a klar.toml (None: not in a project)."""
    d = os.path.abspath(start_dir)
    while True:
        if os.path.isfile(os.path.join(d, MANIFEST)):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def read_manifest(root):
    with open(os.path.join(root, MANIFEST), encoding="utf-8") as f:
        return parse_manifest(f.read(), root)


def dep_root(project_root, owner_root, dep):
    """Where a dependency's files are: a path relative to the manifest that names it, or the project's deps dir."""
    if dep.path is not None:
        return os.path.normpath(os.path.join(owner_root, dep.path))
    return os.path.join(project_root, DEPS_DIR, dep.name)
