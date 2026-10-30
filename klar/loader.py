"""Loads a program: the prelude, the main file and every module it `use`s.

Modules are files. `use geometry.{Point, area}` in `dir/main.klar` loads
`dir/geometry.klar`; `use lib.shapes.{Circle}` loads `dir/lib/shapes.klar`.
In a project (a directory with `klar.toml`, see packages.py) the first part of a `use` may name a dependency:
`use geo.{Point}` loads `<geo>/lib.klar`, `use geo.shapes.{Circle}` loads `<geo>/shapes.klar`.
Modules are checked in dependency order; cycles are errors.
"""
import difflib
import os

from . import nodes as N
from .checker import Checker, Universe
from .diagnostics import Diagnostic, KlarSyntaxError, Span
from .packages import MANIFEST, ManifestError, dep_root, find_root, parse_manifest

PRELUDE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prelude.klar")
STD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "std")
RT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rt")


BROKEN = "broken"     # a manifest with errors (already reported)


class Module:
    def __init__(self, name, path, display):
        self.name = name
        self.path = path
        self.display = display
        self.source = ""
        self.program = None
        self.checker = None
        self.exports = {}
        self.import_from = {}   # imported name -> (Module, kind)
        self.failed = False
        self.diags = []
        self.is_sys = False
        self.pkg = None          # the root directory of the package the module belongs to (None: not in a project)


class LoadedProgram:
    def __init__(self, main, modules, universe, diags, sources):
        self.main = main
        self.modules = modules       # dependency order, prelude first, main last
        self.universe = universe
        self.diags = diags
        self.sources = sources

    @property
    def program(self):
        return self.main.program if self.main else None

    def has_errors(self):
        return any(d.severity == "error" for d in self.diags)


class Loader:
    def __init__(self, root):
        self.root = root
        self.universe = Universe()
        self.by_path = {}
        self.order = []
        self.stack = []
        self.diags = []
        self.sources = {}
        self.prelude = None
        self.overlay = {}        # absolute path -> text (unsaved editor buffers win over the disk)
        self.project = find_root(root)   # the directory of the project's klar.toml (None: no project)
        self.manifests = {}      # package root -> Manifest (None: none, or a broken one already reported)
        self.packages = {}       # dependency name -> (its root, the Dependency, the root of the manifest naming it)
        self.dep_names = {}      # dependency root -> its name (module names inside it start with it)

    def error(self, code, msg, span, hint=None):
        self.diags.append(Diagnostic(code, "error", msg, span, hint))

    def display_of(self, path):
        if os.path.abspath(path).startswith(RT_DIR + os.sep):
            return "rt/" + os.path.relpath(path, RT_DIR).replace(os.sep, "/")
        if os.path.abspath(path).startswith(STD_DIR + os.sep):
            return "std/" + os.path.relpath(path, STD_DIR).replace(os.sep, "/")
        try:
            rel = os.path.relpath(path, self.root)
        except ValueError:
            rel = path
        return rel.replace(os.sep, "/")

    # ---- packages ------------------------------------------------------------------------------------------
    def manifest(self, root):
        """The manifest of the package at `root`: a Manifest, None (no klar.toml) or BROKEN (reported). Reading it
        registers its dependencies; a name that another manifest gives a different source is reported (E0608)."""
        if root in self.manifests:
            return self.manifests[root]
        self.manifests[root] = None
        path = os.path.join(root, MANIFEST)
        shown = self.display_of(path)
        text = self.overlay.get(path)
        try:
            if text is None:
                with open(path, encoding="utf-8") as f:
                    text = f.read()
        except OSError:
            return None
        self.sources[shown] = text
        try:
            man = parse_manifest(text, root)
        except ManifestError as ex:
            line = max(ex.line, 1)
            self.error("E0610", f"invalid klar.toml: {ex.message}", Span(shown, line, 1, line, 1),
                       hint="see `klar explain E0610` for the format")
            self.manifests[root] = BROKEN
            return BROKEN
        self.manifests[root] = man
        for name, dep in man.deps.items():
            droot = dep_root(self.project or root, root, dep)
            prev = self.packages.get(name)
            if prev is None:
                self.packages[name] = (droot, dep, root)
                self.dep_names.setdefault(droot, name)
            elif prev[0] != droot or (prev[1].git, prev[1].ref) != (dep.git, dep.ref):
                there = self.display_of(os.path.join(prev[2], MANIFEST))
                self.error("E0608", f"dependency `{name}` is {dep.describe()} here but {prev[1].describe()} in {there}",
                           Span(shown, dep.line, 1, dep.line, 1),
                           hint="a dependency name means one package in the whole program: make the manifests agree")
        return man

    def dependency(self, pkg, name, span):
        """The root of the dependency `name` of the package at `pkg`; None when it is not one; False when it cannot
        be used (reported, or the manifest is broken)."""
        man = self.manifest(pkg) if pkg is not None else None
        if man is BROKEN:
            return False
        if man is None or name not in man.deps:
            return None
        dep = man.deps[name]
        root = self.packages[name][0]          # (the first registration wins; a conflict was reported)
        if not os.path.isfile(os.path.join(root, MANIFEST)):
            where = self.display_of(os.path.join(root, MANIFEST))
            if dep.git is not None:
                self.error("E0609", f"dependency `{name}` is not fetched (no `{where}`)", span,
                           hint="run `klar fetch` in the project directory")
            else:
                self.error("E0609", f"dependency `{name}` is not a package: `{where}` does not exist", span,
                           hint=f"a package is a directory with a klar.toml; check `path` of `{name}` in "
                                f"{self.display_of(os.path.join(pkg, MANIFEST))}")
            return False
        self.manifest(root)       # (its dependencies are registered, and conflicts reported, on first use)
        return root

    def module_name(self, path, pkg, written):
        """A module of a dependency is named after it (`geo`, `geo.shapes`); the project's modules as written."""
        dep = self.dep_names.get(pkg)
        if dep is None:
            return written
        rel = os.path.relpath(path, pkg)[:-len(".klar")].replace(os.sep, ".")
        return dep if rel == "lib" else f"{dep}.{rel}"

    def load(self, path, name, display, source=None, importer_span=None, pkg=None):
        path = os.path.abspath(path)
        if path in self.by_path and path not in self.stack:
            return self.by_path[path]
        if path in self.stack:
            chain = " -> ".join(self.by_path_name(p) for p in self.stack[self.stack.index(path):]) + f" -> {name}"
            self.error("E0602", f"circular import: {chain}", importer_span,
                       hint="move the shared declarations into a third module that both import")
            return None
        m = Module(name, path, display)
        m.pkg = pkg
        m.is_sys = os.path.abspath(path).startswith(RT_DIR + os.sep)
        if source is None and path in self.overlay:
            source = self.overlay[path]
        if source is None:
            try:
                with open(path, encoding="utf-8") as f:
                    source = f.read()
            except OSError as ex:
                self.error("E0601", f"cannot read module `{name}`: {ex.strerror}", importer_span or Span(display, 0, 0, 0, 0))
                m.failed = True
                return m
        m.source = source
        self.sources[display] = source
        self.by_path[path] = m
        # every recoverable syntax error at once (klar/parser.py `parse_recovering`): the module is still checked
        program, syntax_errors = parse_recovering(source, display)
        self.diags.extend(syntax_errors)
        if program is None:
            m.failed = True
            return m
        m.program = program
        self.stack.append(path)
        imports = {}
        if self.prelude is not None and self.prelude.exports:
            for item, entry in self.prelude.exports.items():
                imports[item] = entry
                m.import_from[item] = (self.prelude, entry[0])
        here = os.path.dirname(path)
        for d in m.program.decls:
            if not isinstance(d, N.UseDecl):
                continue
            dep_name = ".".join(d.path)
            dep_pkg = m.pkg
            if d.path[0] == "std":
                dep_path = os.path.join(STD_DIR, *d.path[1:]) + ".klar"
            elif d.path[0] == "rt" and m.is_sys:
                dep_path = os.path.join(RT_DIR, *d.path[1:]) + ".klar"
            else:
                dep_path = os.path.join(here, *d.path) + ".klar"
                package = self.dependency(m.pkg, d.path[0], d.span)
                if package is False and not os.path.exists(dep_path):
                    continue
                if package is False:
                    package = None
                if package is not None:
                    if os.path.exists(dep_path):
                        self.error("E0607", f"`{dep_name}` is both the dependency `{d.path[0]}` and the file "
                                            f"`{self.display_of(dep_path)}`", d.span,
                                   hint="rename the file or the dependency in klar.toml")
                        continue
                    dep_pkg = package
                    dep_path = os.path.join(package, *(d.path[1:] or ["lib"])) + ".klar"
                    if not os.path.exists(dep_path):
                        self.error("E0601", f"module `{dep_name}` not found (looked for "
                                            f"`{self.display_of(dep_path)}`)", d.span,
                                   hint=f"the package `{d.path[0]}` has no such file: "
                                        f"`use {d.path[0]}.{{...}}` loads its lib.klar, "
                                        f"`use {d.path[0]}.name.{{...}}` its name.klar")
                        continue
            if not os.path.exists(dep_path):
                folder = os.path.join(here, *d.path[:-1])
                existing = []
                if os.path.isdir(folder):
                    existing = [f[:-5] for f in os.listdir(folder) if f.endswith(".klar")]
                close = difflib.get_close_matches(d.path[-1], existing, n=1)
                hint = f"did you mean `{'.'.join(d.path[:-1] + [close[0]])}`?" if close else \
                    f"create the file `{self.display_of(dep_path)}` (modules are files next to the importing file)"
                self.error("E0601", f"module `{dep_name}` not found (looked for `{self.display_of(dep_path)}`)",
                           d.span, hint=hint)
                continue
            dep = self.load(dep_path, self.module_name(os.path.abspath(dep_path), dep_pkg, dep_name),
                            self.display_of(dep_path), importer_span=d.span, pkg=dep_pkg)
            if dep is None:
                continue
            if dep.failed:
                self.error("E0601", f"module `{dep_name}` could not be loaded", d.span,
                           hint="fix the errors reported for that file first")
                continue
            for item, sp in zip(d.items, d.item_spans):
                if item in dep.exports:
                    if item in imports and m.import_from.get(item, (None,))[0] is not self.prelude:
                        self.error("E0101", f"`{item}` is imported twice", sp)
                        continue
                    imports[item] = dep.exports[item]
                    m.import_from[item] = (dep, dep.exports[item][0])
                elif dep.checker is not None and dep.checker.private_decl(item) is not None:
                    decl = dep.checker.private_decl(item)
                    kw = {N.FnDecl: "fn", N.ConstDecl: "const", N.TypeDecl: "type", N.EnumDecl: "enum",
                          N.AliasDecl: "type", N.TraitDecl: "trait"}[type(decl)]
                    at = decl.span
                    fix = {"span": Span(at.file, at.line, at.col, at.line, at.col), "text": "pub ", "safe": True}
                    self.diags.append(Diagnostic(
                        "E0606", "error", f"`{item}` is private to module `{dep_name}`", sp,
                        f"mark it public in {dep.display}: `pub {kw} {item}`", fix))
                else:
                    close = difflib.get_close_matches(item, list(dep.exports), n=1)
                    hint = f"did you mean `{close[0]}`?" if close else \
                        f"`{dep_name}` declares: {', '.join(sorted(dep.exports)) or '(nothing)'}"
                    self.error("E0603", f"module `{dep_name}` has no item `{item}`", sp, hint=hint)
        self.stack.pop()
        m.checker = Checker(m.program, display, self.universe, imports, module=name, sys=m.is_sys)
        # names whose import failed (already reported): their uses are not errors again
        m.checker.unresolved = {item for d in m.program.decls if isinstance(d, N.UseDecl) for item in d.items
                                if item not in imports}
        m.diags = m.checker.run()
        if not m.is_sys and not any(d.severity == "error" for d in m.diags):
            from .safety import analyze
            m.diags += analyze(m.checker, m.program)
        self.diags.extend(m.diags)
        m.exports = m.checker.exports()
        self.order.append(m)
        return m

    def by_path_name(self, p):
        m = self.by_path.get(p)
        return m.name if m else os.path.basename(p)

    def load_prelude(self):
        self.prelude = self.load(PRELUDE_PATH, "prelude", "prelude.klar")


def _finish(loader, main):
    runtime = getattr(loader, "runtime", [])
    diags = sorted(loader.diags, key=lambda d: (d.span.file != (main.display if main else ""),
                                                d.span.file, d.span.line, d.span.col))
    lp = LoadedProgram(main, loader.order, loader.universe, diags, loader.sources)
    lp.runtime = runtime
    return lp


def load_path(path, with_runtime=False, overlay=None):
    path = os.path.abspath(path)
    loader = Loader(os.path.dirname(path))
    loader.overlay = {os.path.abspath(k): v for k, v in (overlay or {}).items()}
    loader.load_prelude()
    name = os.path.splitext(os.path.basename(path))[0]
    main = loader.load(path, name, os.path.basename(path), pkg=loader.project)
    if with_runtime:
        load_runtime(loader)
    return _finish(loader, main)


def load_runtime(loader):
    """All runtime files (system Klar) form ONE module `rt`, so they can call each other freely."""
    files = sorted(f for f in os.listdir(RT_DIR) if f.endswith(".klar"))
    decls = []
    first = None
    m = Module("klar_rt", os.path.join(RT_DIR, "<all>"), "rt")
    m.is_sys = True
    for fname in files:
        path = os.path.join(RT_DIR, fname)
        display = "rt/" + fname
        with open(path, encoding="utf-8") as f:
            src = f.read()
        loader.sources[display] = src
        try:
            prog = parse(src, display)
        except KlarSyntaxError as ex:
            loader.diags.append(ex.diag)
            m.failed = True
            continue
        first = first or prog
        decls += prog.decls
    loader.runtime = [m]
    if m.failed or first is None:
        return
    m.program = N.Program(span=first.span, module="klar_rt", decls=decls, file="rt")
    imports = {}
    if loader.prelude is not None:
        for item, entry in loader.prelude.exports.items():
            imports[item] = entry
            m.import_from[item] = (loader.prelude, entry[0])
    m.checker = Checker(m.program, "rt", loader.universe, imports, module="klar_rt", sys=True)
    m.diags = m.checker.run()
    loader.diags.extend(m.diags)


def load_source(source, file="main.klar", root=None, with_runtime=False, overlay=None):
    root = os.path.abspath(root or os.getcwd())
    loader = Loader(root)
    loader.overlay = {os.path.abspath(k): v for k, v in (overlay or {}).items()}
    loader.load_prelude()
    main = loader.load(os.path.join(root, file), os.path.splitext(file)[0], file, source=source, pkg=loader.project)
    if with_runtime:
        load_runtime(loader)
    return _finish(loader, main)


from .parser import parse, parse_recovering  # noqa: E402  (late import keeps module graph simple)
