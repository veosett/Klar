"""Loads a program: the prelude, the main file and every module it `use`s.

Modules are files. `use geometry.{Point, area}` in `dir/main.klar` loads
`dir/geometry.klar`; `use lib.shapes.{Circle}` loads `dir/lib/shapes.klar`.
Modules are checked in dependency order; cycles are errors.
"""
import difflib
import os

from . import nodes as N
from .checker import Checker, Universe
from .diagnostics import Diagnostic, KlarSyntaxError, Span

PRELUDE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prelude.klar")
STD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "std")
RT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rt")


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

    def load(self, path, name, display, source=None, importer_span=None):
        path = os.path.abspath(path)
        if path in self.by_path and path not in self.stack:
            return self.by_path[path]
        if path in self.stack:
            chain = " -> ".join(self.by_path_name(p) for p in self.stack[self.stack.index(path):]) + f" -> {name}"
            self.error("E0602", f"circular import: {chain}", importer_span,
                       hint="move the shared declarations into a third module that both import")
            return None
        m = Module(name, path, display)
        m.is_sys = os.path.abspath(path).startswith(RT_DIR + os.sep)
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
        try:
            m.program = parse(source, display)
        except KlarSyntaxError as ex:
            self.diags.append(ex.diag)
            m.failed = True
            return m
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
            if d.path[0] == "std":
                dep_path = os.path.join(STD_DIR, *d.path[1:]) + ".klar"
            elif d.path[0] == "rt" and m.is_sys:
                dep_path = os.path.join(RT_DIR, *d.path[1:]) + ".klar"
            else:
                dep_path = os.path.join(here, *d.path) + ".klar"
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
            dep = self.load(dep_path, dep_name, self.display_of(dep_path), importer_span=d.span)
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
                else:
                    close = difflib.get_close_matches(item, list(dep.exports), n=1)
                    hint = f"did you mean `{close[0]}`?" if close else \
                        f"`{dep_name}` declares: {', '.join(sorted(dep.exports)) or '(nothing)'}"
                    self.error("E0603", f"module `{dep_name}` has no item `{item}`", sp, hint=hint)
        self.stack.pop()
        m.checker = Checker(m.program, display, self.universe, imports, module=name, sys=m.is_sys)
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


def load_path(path, with_runtime=False):
    path = os.path.abspath(path)
    loader = Loader(os.path.dirname(path))
    loader.load_prelude()
    name = os.path.splitext(os.path.basename(path))[0]
    main = loader.load(path, name, os.path.basename(path))
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


def load_source(source, file="main.klar", root=None, with_runtime=False):
    root = os.path.abspath(root or os.getcwd())
    loader = Loader(root)
    loader.load_prelude()
    main = loader.load(os.path.join(root, file), os.path.splitext(file)[0], file, source=source)
    if with_runtime:
        load_runtime(loader)
    return _finish(loader, main)


from .parser import parse  # noqa: E402  (late import keeps module graph simple)
