"""Fast backend: compiles a checked Klar program to Python source and runs it.

Why this is simple for Klar: values are immutable and shadowing is forbidden, so
every Klar function maps to one Python function with flat locals; lambdas capture
immutable values by default arguments and mutable `var`s through one-element cells.

Anything the generator does not support raises Unsupported, and the caller falls
back to the tree-walking interpreter, so semantics never silently diverge.
Runtime errors are mapped back to Klar spans and a Klar call stack by reading the
Python traceback (zero cost on the happy path).
"""
import re
import sys

from . import nodes as N
from .builtins import GLOBALS, METHODS
from .diagnostics import BUILTIN_SPAN, Span
from .errors import KlarRuntimeError
from .values import (UNIT, KMap, NONE, Record, Variant, err, ok, show, some)

GEN_FILE = "<klar-compiled>"
MAX_DEPTH = 10000


class Unsupported(Exception):
    pass


class _Early(Exception):
    """Raised by `?` (and returning match arms in expression position)."""

    def __init__(self, value):
        self.value = value


def mangle_module(name):
    return re.sub(r"\W", "_", name)


# ---------------------------------------------------------------------------
# runtime helpers referenced by generated code
# ---------------------------------------------------------------------------
def _try(v):
    if v.name == "Some" or v.name == "Ok":
        return v.values[0]
    raise _Early(v)


def _early(v):
    raise _Early(v)


def _idiv(a, b, sp):
    if b == 0:
        raise KlarRuntimeError("R0001", "division by zero", sp)
    q = abs(a) // abs(b)
    return -q if (a < 0) != (b < 0) else q


def _imod(a, b, sp):
    if b == 0:
        raise KlarRuntimeError("R0001", "division by zero", sp)
    q = abs(a) // abs(b)
    if (a < 0) != (b < 0):
        q = -q
    return a - b * q


def _fdiv(a, b, sp):
    if b == 0:
        raise KlarRuntimeError("R0001", "division by zero", sp)
    return a / b


def _fmod(a, b, sp):
    if b == 0:
        raise KlarRuntimeError("R0001", "division by zero", sp)
    return a - b * int(a / b)


def _map(xs, f):
    return tuple(map(f, xs))


def _filter(xs, f):
    return tuple([x for x in xs if f(x)])


def _fold(xs, init, f):
    acc = init
    for x in xs:
        acc = f(acc, x)
    return acc


def _any(xs, f):
    for x in xs:
        if f(x):
            return True
    return False


def _all(xs, f):
    for x in xs:
        if not f(x):
            return False
    return True


def _count(xs, f):
    n = 0
    for x in xs:
        if f(x):
            n += 1
    return n


def _get(xs, i):
    return Variant("Option", "Some", (xs[i],), ("value",)) if 0 <= i < len(xs) else NONE


def _with(base, upd):
    f = dict(base.fields)
    f.update(upd)
    return Record(base.type_name, f)


def _mkrec(name, order, given):
    return Record(name, {k: given[k] for k in order})


def _nomatch(v, sp):
    raise KlarRuntimeError("R0099", f"internal: no match arm for {show(v, False)}", sp)


def _fail(code, msg, sp, details):
    raise KlarRuntimeError(code, msg, sp, [f"{k} = {show(v, False)}" for k, v in details])


class Ctx:
    """The `it` object built-ins receive."""

    def __init__(self, out, inp, err_stream, cli_args, sources):
        self.out = out
        self.inp = inp
        self.err = err_stream
        self.cli_args = tuple(cli_args)
        self.sources = {k: v.split("\n") for k, v in sources.items()}

    def call_value(self, f, args, sp):
        return f(*args)

    def src(self, span):
        lines = self.sources.get(span.file)
        if not lines or span.line <= 0:
            return "?"
        if span.line != span.end_line:
            return lines[span.line - 1][span.col - 1:].strip() + " ..."
        return lines[span.line - 1][span.col - 1:span.end_col - 1]


# ---------------------------------------------------------------------------
# analysis helpers
# ---------------------------------------------------------------------------
def walk_shallow(node):
    """Walk a subtree without entering nested lambdas."""
    yield node
    for child in children(node):
        if isinstance(child, N.Lambda):
            yield child
            continue
        yield from walk_shallow(child)


def children(node):
    from dataclasses import fields
    for f in fields(node):
        v = getattr(node, f.name)
        if isinstance(v, N.Node):
            yield v
        elif isinstance(v, list):
            for x in v:
                if isinstance(x, N.Node):
                    yield x


def declared_names(fn_like):
    """Locals declared directly in a function or lambda (not nested lambdas): name -> mutable?"""
    out = {}
    for p in fn_like.params:
        out[p.name] = False
    body = fn_like.body
    for n in walk_shallow(body) if isinstance(body, N.Node) else []:
        if isinstance(n, N.Let) and n.name != "_":
            out[n.name] = out.get(n.name, False) or n.mutable
        elif isinstance(n, N.For):
            out.setdefault(n.var, False)
        elif isinstance(n, N.PBind):
            out.setdefault(n.name, False)
    return out


def used_names(node):
    return {n.name for n in N.walk(node) if isinstance(n, N.Name)} | \
           {n.name for n in N.walk(node) if isinstance(n, N.Assign)}


def contains_try(node):
    for n in walk_shallow(node):
        if isinstance(n, N.Try):
            return True
    return False


class FnScope:
    def __init__(self, locals_, boxed, parent=None):
        self.locals = locals_      # name -> mutable
        self.boxed = boxed         # names stored in one-element cells
        self.parent = parent
        self.needs_early = False

    def is_local(self, name):
        s = self
        while s is not None:
            if name in s.locals:
                return True
            s = s.parent
        return False

    def is_boxed(self, name):
        s = self
        while s is not None:
            if name in s.locals:
                return name in s.boxed
            s = s.parent
        return False


# ---------------------------------------------------------------------------
# generator
# ---------------------------------------------------------------------------
class Gen:
    def __init__(self, loaded):
        self.loaded = loaded
        self.universe = loaded.universe
        self.lines = []
        self.line_spans = [None]          # generated line number -> Klar span
        self.spans = []
        self.span_index = {}
        self.fn_names = {}                # python function name -> Klar name
        self.cur_span = BUILTIN_SPAN
        self.counter = 0
        self.scope = None
        self.module = None
        self.pre = None
        self.expr_bound = set()

    # ---- output -------------------------------------------------------------
    def emit(self, level, text):
        self.lines.append("    " * level + text)
        self.line_spans.append(self.cur_span)

    def sp(self, span):
        key = id(span)
        if key not in self.span_index:
            self.span_index[key] = len(self.spans)
            self.spans.append(span)
        return f"_S[{self.span_index[key]}]"

    def tmp(self, prefix="_t"):
        self.counter += 1
        return f"{prefix}{self.counter}"

    # ---- names --------------------------------------------------------------
    def fn_py(self, module_name, name):
        return f"F_{mangle_module(module_name)}__{name}"

    def const_py(self, module_name, name):
        return f"C_{mangle_module(module_name)}__{name}"

    def resolve_global(self, name):
        """Python expression for a module-level name (fn/const/builtin) visible in the current module."""
        m = self.module
        chk = m.checker
        if name in m.import_from:
            dep, kind = m.import_from[name]
            return self.fn_py(dep.name, name) if kind == "fn" else self.const_py(dep.name, name)
        if name in chk.consts:
            return self.const_py(m.name, name)
        sig = chk.fns.get(name)
        if sig is not None and sig.decl is not None:
            return self.fn_py(sig.module, name)
        if name in GLOBALS:
            return f"B_{name}_value"
        if name == "None":
            return "NONE"
        raise Unsupported(f"unresolved name {name}")

    def var(self, name):
        py = "v_" + name
        return py + "[0]" if self.scope.is_boxed(name) else py

    # ---- program ------------------------------------------------------------
    def program(self):
        for m in self.loaded.modules:
            self.module = m
            for d in m.program.decls:
                if isinstance(d, N.FnDecl):
                    self.function(d)
        # constants, in module order (dependencies first)
        for m in self.loaded.modules:
            self.module = m
            for d in m.program.decls:
                if isinstance(d, N.ConstDecl):
                    self.cur_span = d.span
                    self.scope = FnScope({}, set())
                    self.pre = []
                    value = self.expr(d.value)
                    for level, line in self.pre:
                        self.emit(level, line)
                    self.emit(0, f"{self.const_py(m.name, d.name)} = {value}")
        return "\n".join(self.lines) + "\n"

    def function(self, d: N.FnDecl):
        py = self.fn_py(self.module.name, d.name)
        self.fn_names[py] = d.name
        locals_ = declared_names(d)
        boxed = self.boxed_names(d, locals_)
        self.scope = FnScope(locals_, boxed)
        self.cur_span = d.span
        params = ", ".join("v_" + p.name for p in d.params)
        has_ensures = bool(d.ensures)
        body_name = py + "__body" if has_ensures else py
        if has_ensures:
            self.fn_names[body_name] = d.name
        self.emit(0, f"def {body_name}({params}):")
        level = 1
        for p in d.params:
            if p.name in boxed:
                self.emit(level, f"v_{p.name} = [v_{p.name}]")
        if d.requires and not has_ensures:
            self.contracts(d, d.requires, "R0002", "precondition", level)
        early = contains_try(d.body) or self.has_early_arm(d.body)
        if early:
            self.emit(level, "try:")
            self.block_stmts(d.body, level + 1)
            self.emit(level + 1, "return UNIT")
            self.emit(level, "except _Early as _e:")
            self.emit(level + 1, "return _e.value")
        else:
            self.block_stmts(d.body, level)
            self.emit(level, "return UNIT")
        if has_ensures:
            self.cur_span = d.span
            self.emit(0, f"def {py}({params}):")
            self.scope = FnScope({p.name: False for p in d.params} | {"result": False}, set())
            if d.requires:
                self.contracts(d, d.requires, "R0002", "precondition", 1)
            self.emit(1, f"v_result = {body_name}({params})")
            self.contracts(d, d.ensures, "R0003", "postcondition", 1)
            self.emit(1, "return v_result")
        self.emit(0, "")

    def contracts(self, d, conds, code, kind, level):
        for c in conds:
            self.cur_span = c.span
            self.pre = []
            cond = self.expr(c)
            for lv, line in self.pre:
                self.emit(level + lv, line)
            names = sorted({n.name for n in N.walk(c) if isinstance(n, N.Name) and self.scope.is_local(n.name)})
            details = "[" + ", ".join(f"({n!r}, {self.var(n)})" for n in names) + "]"
            text = self.src_text(c.span)
            msg = f"{kind} `{text}` of `{d.name}` violated"
            self.emit(level, f"if not ({cond}):")
            self.emit(level + 1, f"_fail({code!r}, {msg!r}, {self.sp(c.span)}, {details})")

    def src_text(self, span):
        lines = self.loaded.sources.get(span.file, "").split("\n")
        if span.line <= 0 or span.line > len(lines):
            return "?"
        line = lines[span.line - 1]
        return line[span.col - 1:span.end_col - 1] if span.line == span.end_line else line[span.col - 1:].strip()

    def boxed_names(self, fn_like, locals_):
        mutable = {n for n, m in locals_.items() if m}
        boxed = set()
        if not mutable:
            return boxed
        for n in walk_shallow(fn_like.body):
            if isinstance(n, N.Lambda):
                boxed |= mutable & used_names(n)
        return boxed

    def has_early_arm(self, body):
        """Expression-position match arms that are `{ return x }` compile to raise _Early."""
        for n in walk_shallow(body):
            if isinstance(n, N.Match):
                for a in n.arms:
                    if isinstance(a.body, N.Block):
                        return True
        return False

    # ---- statements -----------------------------------------------------------
    def block_stmts(self, block, level):
        if not block.stmts:
            self.emit(level, "pass")
            return
        for s in block.stmts:
            self.stmt(s, level)

    def flush_pre(self, level):
        for lv, line in self.pre:
            self.emit(level + lv, line)
        self.pre = []

    def stmt(self, s, level):
        self.cur_span = s.span
        t = type(s)
        if t is N.Let:
            if isinstance(s.value, N.Match):
                target = None if s.name == "_" else ("box" if self.scope.is_boxed(s.name) else "v_" + s.name)
                self.lifted_match(s.value, level, ("assign", target))
                return
            self.pre = []
            v = self.expr(s.value)
            self.flush_pre(level)
            if s.name == "_":
                self.emit(level, v)
            elif self.scope.is_boxed(s.name):
                self.emit(level, f"v_{s.name} = [{v}]")
            else:
                self.emit(level, f"v_{s.name} = {v}")
        elif t is N.Assign:
            target = self.var(s.name)
            if isinstance(s.value, N.Match):
                self.lifted_match(s.value, level, ("assign", target))
                return
            self.pre = []
            v = self.expr(s.value)
            self.flush_pre(level)
            self.emit(level, f"{target} = {v}")
        elif t is N.Return:
            if s.value is None:
                self.emit(level, "return UNIT")
                return
            if isinstance(s.value, N.Match):
                self.lifted_match(s.value, level, ("return",))
                return
            self.pre = []
            v = self.expr(s.value)
            self.flush_pre(level)
            self.emit(level, f"return {v}")
        elif t is N.ExprStmt:
            if isinstance(s.expr, N.Match):
                self.lifted_match(s.expr, level, ("discard",))
                return
            self.pre = []
            v = self.expr(s.expr)
            self.flush_pre(level)
            self.emit(level, v)
        elif t is N.If:
            self.if_stmt(s, level, "if")
        elif t is N.While:
            self.pre = []
            c = self.expr(s.cond)
            if self.pre:
                raise Unsupported("lambda with block body in while condition")
            self.emit(level, f"while {c}:")
            self.block_stmts(s.body, level + 1)
        elif t is N.For:
            self.pre = []
            it = self.expr(s.iter)
            self.flush_pre(level)
            self.emit(level, f"for v_{s.var} in {it}:")
            self.block_stmts(s.body, level + 1)
        elif t is N.Break:
            self.emit(level, "break")
        elif t is N.Continue:
            self.emit(level, "continue")
        elif t is N.Assert:
            self.assert_stmt(s, level)
        else:
            raise Unsupported(t.__name__)

    def if_stmt(self, s, level, kw):
        self.cur_span = s.span
        self.pre = []
        c = self.expr(s.cond)
        if self.pre:
            if kw == "elif":
                raise Unsupported("lambda with block body in else-if condition")
            self.flush_pre(level)
        self.emit(level, f"{kw} {c}:")
        self.block_stmts(s.then, level + 1)
        if isinstance(s.else_, N.If):
            self.if_stmt(s.else_, level, "elif")
        elif s.else_ is not None:
            self.emit(level, "else:")
            self.block_stmts(s.else_, level + 1)

    def assert_stmt(self, s, level):
        c = s.cond
        self.pre = []
        text = self.src_text(c.span)
        if isinstance(c, N.Binary) and c.op in ("==", "!=", "<", ">", "<=", ">="):
            lt, rt = self.tmp(), self.tmp()
            left = self.expr(c.left)
            right = self.expr(c.right)
            self.flush_pre(level)
            self.emit(level, f"{lt} = {left}")
            self.emit(level, f"{rt} = {right}")
            cond = f"{lt} {c.op} {rt}"
            details = f"[('left', {lt}), ('right', {rt})]"
        else:
            cond = self.expr(c)
            self.flush_pre(level)
            names = sorted({n.name for n in N.walk(c) if isinstance(n, N.Name) and self.scope.is_local(n.name)})
            details = "[" + ", ".join(f"({n!r}, {self.var(n)})" for n in names) + "]"
        msg = f"assertion failed: `{text}`"
        self.emit(level, f"if not ({cond}):")
        if s.message is not None:
            self.pre = []
            m = self.expr(s.message)
            self.flush_pre(level + 1)
            self.emit(level + 1, f"_fail('R0005', {msg!r} + ' — ' + {m}, {self.sp(s.span)}, {details})")
        else:
            self.emit(level + 1, f"_fail('R0005', {msg!r}, {self.sp(s.span)}, {details})")

    # ---- match ------------------------------------------------------------------
    def lifted_match(self, m, level, target):
        """match as a statement: if/elif chain; arms assign/return/discard their value."""
        self.cur_span = m.span
        self.pre = []
        subj = self.expr(m.subject)
        self.flush_pre(level)
        s = self.tmp("_s")
        self.emit(level, f"{s} = {subj}")
        first = True
        for arm in m.arms:
            self.cur_span = arm.span
            saved_bound = self.expr_bound
            self.expr_bound = set()
            self.pre = []
            test = self.pattern_test(arm.pattern, s)
            if arm.guard is not None:
                g = self.expr(arm.guard)
                test = f"({test}) and ({g})"
            self.expr_bound = saved_bound
            if self.pre:
                raise Unsupported("lambda with block body in a match guard")
            self.emit(level, f"{'if' if first else 'elif'} {test}:")
            first = False
            if isinstance(arm.body, N.Block):
                self.block_stmts(arm.body, level + 1)
                if target[0] == "assign" and target[1] is not None:
                    self.assign_target(target[1], "UNIT", level + 1)
                elif target[0] == "return":
                    self.emit(level + 1, "return UNIT")
            elif isinstance(arm.body, N.Match):
                self.lifted_match(arm.body, level + 1, target)
            else:
                self.pre = []
                v = self.expr(arm.body)
                self.flush_pre(level + 1)
                if target[0] == "assign":
                    if target[1] is None:
                        self.emit(level + 1, v)
                    else:
                        self.assign_target(target[1], v, level + 1)
                elif target[0] == "return":
                    self.emit(level + 1, f"return {v}")
                else:
                    self.emit(level + 1, v)
        self.emit(level, "else:")
        self.emit(level + 1, f"_nomatch({s}, {self.sp(m.span)})")

    def assign_target(self, target, value, level):
        if target == "box":
            raise Unsupported("boxed let from match")
        self.emit(level, f"{target} = {value}")

    def pattern_test(self, p, s):
        t = type(p)
        if t is N.PWild:
            return "True"
        if t is N.PBind:
            self.expr_bound.add(p.name)
            if self.scope.is_boxed(p.name):
                raise Unsupported("captured mutable pattern variable")
            return f"((v_{p.name} := {s}) is v_{p.name})"
        if t is N.PLit:
            return f"({s} == {self.literal(p.value)})"
        if t is N.PVariant:
            parts = [f"{s}.name == {p.variant!r}"]
            for i, a in enumerate(p.args):
                if isinstance(a, N.PWild):
                    continue
                parts.append(self.pattern_test(a, f"{s}.values[{i}]"))
            return " and ".join(parts) if len(parts) > 1 else parts[0]
        raise Unsupported(t.__name__)

    def literal(self, v):
        if isinstance(v, bool):
            return "True" if v else "False"
        return repr(v)

    def expr_match(self, m):
        """match in expression position: a chain of conditional expressions."""
        subj = self.expr(m.subject)
        s = self.tmp("_s")
        pieces = []
        for i, arm in enumerate(m.arms):
            test = self.pattern_test(arm.pattern, s)
            if i == 0:
                test = f"(({s} := {subj}) is {s}) and {test}"
            if arm.guard is not None:
                test = f"({test}) and ({self.expr(arm.guard)})"
            if isinstance(arm.body, N.Block):
                body = arm.body
                if len(body.stmts) == 1 and isinstance(body.stmts[0], N.Return) and body.stmts[0].value is not None:
                    self.scope.needs_early = True
                    value = f"_early({self.expr(body.stmts[0].value)})"
                else:
                    raise Unsupported("block arm in expression-position match")
            else:
                value = self.expr(arm.body)
            pieces.append((test, value))
        out = f"_nomatch({s}, {self.sp(m.span)})"
        for test, value in reversed(pieces):
            out = f"({value} if {test} else {out})"
        return out

    # ---- expressions ---------------------------------------------------------------
    def expr(self, e):
        return getattr(self, "x_" + type(e).__name__)(e)

    def x_IntLit(self, e):
        return repr(e.value) if e.value >= 0 else f"({e.value!r})"

    def x_FloatLit(self, e):
        return repr(e.value) if e.value >= 0 else f"({e.value!r})"

    def x_BoolLit(self, e):
        return "True" if e.value else "False"

    def x_UnitLit(self, e):
        return "UNIT"

    def x_StrLit(self, e):
        parts = []
        for p in e.parts:
            if isinstance(p, str):
                parts.append(repr(p))
            else:
                parts.append(f"_show({self.expr(p)}, True)")
        if not parts:
            return "''"
        return "(" + " + ".join(parts) + ")" if len(parts) > 1 else parts[0]

    def x_ListLit(self, e):
        items = [self.expr(x) for x in e.items]
        return "(" + "".join(f"{x}, " for x in items) + ")"

    def x_MapLit(self, e):
        return "KMap({" + ", ".join(f"{self.expr(en.key)}: {self.expr(en.value)}" for en in e.entries) + "})"

    def x_Name(self, e):
        if self.scope.is_local(e.name):
            return self.var(e.name)
        return self.resolve_global(e.name)

    def x_Unary(self, e):
        v = self.expr(e.operand)
        return f"(not {v})" if e.op == "not" else f"(-{v})"

    def x_Binary(self, e):
        op = e.op
        l = self.expr(e.left)
        r = self.expr(e.right)
        if op in ("and", "or"):
            return f"({l} {op} {r})"
        if op in ("/", "%"):
            ty = getattr(e, "ty", None)
            if ty == "Int":
                # fast path: non-negative dividend and positive divisor behave the same as Python's // and %;
                # everything else (negative operands, zero) goes through the exact helper.
                fn = "_idiv" if op == "/" else "_imod"
                pyop = "//" if op == "/" else "%"
                if isinstance(e.right, N.IntLit) and e.right.value > 0:
                    b = e.right.value
                    if isinstance(e.left, (N.Name, N.IntLit)):
                        a = l
                        bind = l
                    else:
                        a = self.tmp("_a")
                        bind = f"({a} := {l})"
                    return f"({a} {pyop} {b} if {bind} >= 0 else {fn}({a}, {b}, {self.sp(e.span)}))"
                a, b = self.tmp("_a"), self.tmp("_b")
                # `&` (not `and`) so both operands are always evaluated, left to right
                return (f"({a} {pyop} {b} if (({a} := {l}) >= 0) & (({b} := {r}) > 0) "
                        f"else {fn}({a}, {b}, {self.sp(e.span)}))")
            elif ty == "Float":
                fn = "_fdiv" if op == "/" else "_fmod"
            else:
                raise Unsupported("untyped division")
            return f"{fn}({l}, {r}, {self.sp(e.span)})"
        return f"({l} {op} {r})"

    def args_code(self, args, param_names=None):
        out = []
        for a in args:
            v = self.expr(a.value)
            out.append(f"v_{a.name}={v}" if a.name is not None else v)
        return ", ".join(out)

    def builtin_list_args(self, sig_params, args, recv=None):
        """Built-ins take a positional list; named args are placed by parameter order."""
        names = [p.name for p in sig_params]
        if recv is not None:
            names = names[1:]
        vals = {}
        pos = 0
        for a in args:
            v = self.expr(a.value)
            if a.name is None:
                vals[names[pos]] = v
                pos += 1
            else:
                vals[a.name] = v
        ordered = [vals[n] for n in names if n in vals]
        if recv is not None:
            ordered = [recv] + ordered
        return "[" + ", ".join(ordered) + "]"

    def x_Call(self, e):
        c = e.callee
        if isinstance(c, N.Name) and not self.scope.is_local(c.name):
            name = c.name
            m = self.module
            if name in m.import_from or (name in m.checker.fns and m.checker.fns[name].decl is not None):
                return f"{self.resolve_global(name)}({self.args_code(e.args)})"
            if name in GLOBALS:
                if name == "range" and not any(a.name for a in e.args):
                    return f"tuple(range({self.expr(e.args[0].value)}, {self.expr(e.args[1].value)}))"
                if name == "Some":
                    return f"some({self.expr(e.args[0].value)})"
                if name == "Ok":
                    return f"ok({self.expr(e.args[0].value)})"
                if name == "Err":
                    return f"err({self.expr(e.args[0].value)})"
                from .builtins import parsed
                decl = parsed(GLOBALS[name][0])
                return f"B_{name}(_ctx, {self.builtin_list_args(decl.params, e.args)}, {self.sp(e.span)})"
            raise Unsupported(f"call of {name}")
        f = self.expr(c)
        if any(a.name for a in e.args):
            raise Unsupported("named args on function value")
        return f"{f}({self.args_code(e.args)})"

    def is_type_ref(self, obj):
        return isinstance(obj, N.Name) and not self.scope.is_local(obj.name)

    def variant(self, enum, vname, args):
        fields = [f for f, _ in self.universe.enums[enum].variants[vname]]
        vals = {}
        pos = 0
        for a in args:
            v = self.expr(a.value)
            if a.name is None:
                vals[fields[pos]] = v
                pos += 1
            else:
                vals[a.name] = v
        values = "(" + "".join(f"{vals[f]}, " for f in fields) + ")"
        return f"Variant({enum!r}, {vname!r}, {values}, {tuple(fields)!r})"

    def x_MethodCall(self, e):
        res = getattr(e, "resolved", None)
        if res is None:
            raise Unsupported("unresolved method call")
        kind = res[0]
        if kind == "variant":
            return self.variant(res[1], res[2], e.args)
        recv = self.expr(e.obj)
        if kind == "to_str":
            return f"_show({recv}, True)"
        if kind == "field_fn":
            return f"{recv}.fields[{e.method!r}]({self.args_code(e.args)})"
        if kind == "builtin":
            _, owner, m = res
            fast = self.fast_method(owner, m, recv, e.args)
            if fast is not None:
                return fast
            from .builtins import parsed
            decl = parsed(METHODS[owner][m][0])
            return f"M_{owner}_{m}(_ctx, {self.builtin_list_args(decl.params, e.args, recv)}, {self.sp(e.span)})"
        if kind == "ufcs":
            _, module_name, fname = res
            rest = self.args_code(e.args)
            return f"{self.fn_py(module_name, fname)}({recv}{', ' + rest if rest else ''})"
        raise Unsupported(kind)

    FAST_HOF = {("List", "map"): "_map", ("List", "filter"): "_filter", ("List", "any"): "_any",
                ("List", "all"): "_all", ("List", "count"): "_count"}

    def fast_method(self, owner, m, recv, args):
        """Inline the hottest built-ins (semantics identical to klar/builtins.py, verified by tests)."""
        if any(a.name for a in args):
            return None
        a = [self.expr(x.value) for x in args]
        if (owner, m) in self.FAST_HOF:
            return f"{self.FAST_HOF[(owner, m)]}({recv}, {a[0]})"
        if (owner, m) == ("List", "fold"):
            return f"_fold({recv}, {a[0]}, {a[1]})"
        if (owner, m) in (("List", "len"), ("Str", "len"), ("Map", "len")):
            return f"len({recv}{'.d' if owner == 'Map' else ''})"
        if (owner, m) in (("List", "is_empty"), ("Str", "is_empty")):
            return f"(len({recv}) == 0)"
        if (owner, m) == ("List", "push"):
            return f"({recv} + ({a[0]},))"
        if (owner, m) == ("List", "get"):
            return f"_get({recv}, {a[0]})"
        if (owner, m) == ("List", "sum"):
            return f"sum({recv})"
        if (owner, m) == ("Str", "ends_with"):
            return f"{recv}.endswith({a[0]})"
        if (owner, m) == ("Str", "starts_with"):
            return f"{recv}.startswith({a[0]})"
        if (owner, m) == ("Int", "to_float"):
            return f"float({recv})"
        return None

    def x_FieldAccess(self, e):
        if self.is_type_ref(e.obj) and e.obj.name in self.universe.enums:
            return f"Variant({e.obj.name!r}, {e.name!r})"
        return f"{self.expr(e.obj)}.fields[{e.name!r}]"

    def x_Try(self, e):
        self.scope.needs_early = True
        return f"_try({self.expr(e.expr)})"

    def x_RecordLit(self, e):
        order = list(self.universe.records[e.type_name].fields)
        given = [f.name for f in e.fields]
        items = ", ".join(f"{f.name!r}: {self.expr(f.value)}" for f in e.fields)
        if given == order:
            return f"Record({e.type_name!r}, {{{items}}})"
        return f"_mkrec({e.type_name!r}, {tuple(order)!r}, {{{items}}})"

    def x_WithExpr(self, e):
        items = ", ".join(f"{f.name!r}: {self.expr(f.value)}" for f in e.fields)
        return f"_with({self.expr(e.base)}, {{{items}}})"

    def x_Match(self, e):
        return self.expr_match(e)

    def x_Lambda(self, e):
        own = declared_names(e)
        free = sorted(n for n in used_names(e.body) if n not in own and self.scope.is_local(n))
        defaults = "".join(f", v_{n}=v_{n}" for n in free)
        params = ", ".join("v_" + p.name for p in e.params)
        sig = (params + defaults) if params else defaults.lstrip(", ")
        outer = self.scope
        boxed = self.boxed_names(e, own)
        inner = FnScope(own, boxed, parent=outer)
        # names captured from outer scopes are locals of the lambda now (default args), boxing as outer
        simple = (not isinstance(e.body, N.Block) and not contains_try(e.body)
                  and not isinstance(e.body, N.Match) and not boxed
                  and not any(isinstance(n, N.Match) and any(isinstance(a.body, N.Block) for a in n.arms)
                              for n in walk_shallow(e.body)))
        if not simple and self.expr_bound & set(free):
            raise Unsupported("hoisted lambda capturing a pattern variable in expression position")
        self.scope = inner
        try:
            if simple:
                body = self.expr(e.body)
                return f"(lambda {sig}: {body})"
            # hoist a def before the current statement
            name = self.tmp("_lam")
            self.fn_names[name] = "<lambda>"
            saved_pre = self.pre
            self.pre = []
            sub = Gen.__new__(Gen)
            sub.__dict__.update(self.__dict__)
            sub.lines = []
            sub.line_spans = []
            sub.pre = []
            sub.scope = inner
            sub.emit(0, f"def {name}({sig}):")
            for p in e.params:
                if p.name in boxed:
                    sub.emit(1, f"v_{p.name} = [v_{p.name}]")
            body = e.body if isinstance(e.body, N.Block) else N.Block(span=e.body.span, stmts=[
                N.Return(span=e.body.span, value=e.body)])
            early = contains_try(body) or self.has_early_arm(body)
            if early:
                sub.emit(1, "try:")
                sub.block_stmts(body, 2)
                sub.emit(2, "return UNIT")
                sub.emit(1, "except _Early as _e:")
                sub.emit(2, "return _e.value")
            else:
                sub.block_stmts(body, 1)
                sub.emit(1, "return UNIT")
            self.counter = sub.counter
            # the def is emitted as pre-statements relative to the current statement's level
            pre = [(0, line) for line in sub.lines]
            self.pending_spans = getattr(self, "pending_spans", [])
            self.pre = saved_pre + pre
            return name
        finally:
            self.scope = outer


def compile_program(loaded):
    """Returns (python_source, namespace) ready to exec, or raises Unsupported."""
    g = Gen(loaded)
    src = g.program()
    ns = {
        "__name__": "klar_compiled", "_S": g.spans, "UNIT": UNIT, "NONE": NONE, "KMap": KMap,
        "Record": Record, "Variant": Variant, "some": some, "ok": ok, "err": err, "_show": show,
        "_try": _try, "_early": _early, "_Early": _Early, "_idiv": _idiv, "_imod": _imod, "_fdiv": _fdiv,
        "_fmod": _fmod, "_with": _with, "_map": _map, "_filter": _filter, "_fold": _fold, "_any": _any,
        "_all": _all, "_count": _count, "_get": _get, "_mkrec": _mkrec, "_nomatch": _nomatch, "_fail": _fail,
    }
    for name, (_, impl) in GLOBALS.items():
        ns[f"B_{name}"] = impl
    for owner, ms in METHODS.items():
        for name, (_, impl) in ms.items():
            ns[f"M_{owner}_{name}"] = impl
    return src, ns, g


class CompiledProgram:
    def __init__(self, loaded, out=None, inp=None, err_stream=None, cli_args=()):
        self.loaded = loaded
        self.src, self.ns, self.gen = compile_program(loaded)
        self.ctx = Ctx(out or sys.stdout, inp or sys.stdin, err_stream or sys.stderr, cli_args, loaded.sources)
        self.ns["_ctx"] = self.ctx
        for name, (_, impl) in GLOBALS.items():
            self.ns[f"B_{name}_value"] = (lambda impl: lambda *a: impl(self.ctx, list(a), BUILTIN_SPAN))(impl)
        self.code = compile(self.src, GEN_FILE, "exec")

    def run_main(self):
        old = sys.getrecursionlimit()
        sys.setrecursionlimit(MAX_DEPTH * 3 + 200)
        try:
            exec(self.code, self.ns)
            main = self.ns[self.gen.fn_py(self.loaded.main.name, "main")]
            result = main()
        except KlarRuntimeError as ex:
            self.enrich(ex, sys.exc_info()[2])
            raise
        except RecursionError:
            tb = sys.exc_info()[2]
            frames = self.klar_frames(tb)
            span = frames[-1][1] if frames else BUILTIN_SPAN
            ex = KlarRuntimeError("R0006", f"stack overflow: more than {MAX_DEPTH} nested calls", span,
                                  hint="check the base case of the recursion")
            ex.stack = self.stack_from(frames)
            raise ex
        finally:
            sys.setrecursionlimit(old)
        if isinstance(result, Variant) and result.enum == "Result" and result.name == "Err":
            main_decl = next(d for d in self.loaded.main.program.decls
                             if isinstance(d, N.FnDecl) and d.name == "main")
            raise KlarRuntimeError("R0007", f"main returned {show(result, False)}", main_decl.name_span)
        return result

    def klar_frames(self, tb):
        frames = []
        while tb is not None:
            f = tb.tb_frame
            if f.f_code.co_filename == GEN_FILE:
                name = self.gen.fn_names.get(f.f_code.co_name, f.f_code.co_name)
                line = tb.tb_lineno
                span = self.gen.line_spans[line] if line < len(self.gen.line_spans) else BUILTIN_SPAN
                frames.append((name, span, f))
            tb = tb.tb_next
        return frames

    def stack_from(self, frames):
        stack = []
        for i, (name, _span, _f) in enumerate(frames):
            call_span = frames[i - 1][1] if i > 0 else self.main_span()
            stack.append((name, call_span))
        if len(stack) > 200:
            stack = stack[:100] + stack[-100:]
        return stack

    def main_span(self):
        for d in self.loaded.main.program.decls:
            if isinstance(d, N.FnDecl) and d.name == "main":
                return d.name_span
        return BUILTIN_SPAN

    def enrich(self, ex, tb):
        frames = self.klar_frames(tb)
        if not ex.stack:
            ex.stack = self.stack_from(frames)
        if ex.code == "R0001" and frames and not ex.details:
            f = frames[-1][2]
            ex.details = [f"{k[2:]} = {show(v[0] if isinstance(v, list) else v, False)}"
                          for k, v in f.f_locals.items() if k.startswith("v_") and
                          k[2:] in self.src_names(ex.span)]

    def src_names(self, span):
        text = self.gen.src_text(span)
        return set(re.findall(r"[a-z_][a-z0-9_]*", text))
