"""Tree-walking interpreter for checked Klar programs (with an optional profiler)."""
import io
import random
import sys
import threading
import time

from . import nodes as N
from .builtins import GLOBALS, METHODS, param_names
from .errors import KlarRuntimeError
from .types import TCon, prune, subst
from .values import (UNIT, Builtin, Closure, KMap, NONE, Record, Variant, err, ok, show, some, type_head)

MAX_DEPTH = 10000


class ReturnSignal(Exception):
    def __init__(self, value):
        self.value = value


class BreakSignal(Exception):
    pass


class ContinueSignal(Exception):
    pass


class Env:
    __slots__ = ("vars", "parent")

    def __init__(self, parent=None, vars=None):
        self.vars = vars if vars is not None else {}
        self.parent = parent

    def get(self, name):
        e = self
        while e is not None:
            v = e.vars
            if name in v:
                return v[name]
            e = e.parent
        raise KeyError(name)

    def has(self, name):
        e = self
        while e is not None:
            if name in e.vars:
                return True
            e = e.parent
        return False

    def set(self, name, value):
        e = self
        while e is not None:
            if name in e.vars:
                e.vars[name] = value
                return
            e = e.parent
        raise KeyError(name)


class Profiler:
    """Deterministic profiler: call counts, inclusive/self time per function, statement counts per line."""

    def __init__(self):
        self.funcs = {}      # key -> [calls, total, self]
        self.lines = {}      # (file, line) -> count
        self.stack = []      # [key, start, child_time]
        self.start = time.perf_counter()
        self.end = None

    def enter(self, key):
        self.stack.append([key, time.perf_counter(), 0.0])

    def exit(self):
        key, start, child = self.stack.pop()
        elapsed = time.perf_counter() - start
        rec = self.funcs.get(key)
        if rec is None:
            rec = self.funcs[key] = [0, 0.0, 0.0]
        rec[0] += 1
        # inclusive time is only added for the outermost active frame of a recursive function
        if not any(f[0] == key for f in self.stack):
            rec[1] += elapsed
        rec[2] += elapsed - child
        if self.stack:
            self.stack[-1][2] += elapsed

    def line(self, span):
        k = (span.file, span.line)
        self.lines[k] = self.lines.get(k, 0) + 1

    def finish(self):
        self.end = time.perf_counter()

    def total(self):
        return (self.end or time.perf_counter()) - self.start


class Interpreter:
    def __init__(self, loaded, out=None, inp=None, err_stream=None, cli_args=()):
        self.loaded = loaded
        self.universe = loaded.universe
        self.sources = {k: v.split("\n") for k, v in loaded.sources.items()}
        self.out = out or sys.stdout
        self.inp = inp or sys.stdin
        self.err = err_stream or sys.stderr
        self.cli_args = tuple(cli_args)
        self.prof = None
        self.records = {name: list(info.fields) for name, info in self.universe.records.items()}
        self.enums = {name: {v: [f for f, _ in fs] for v, fs in info.variants.items()}
                      for name, info in self.universe.enums.items()}
        self.builtins_env = Env()
        for name, (sig, impl) in GLOBALS.items():
            self.builtins_env.vars[name] = Builtin(name, impl, param_names(sig))
        self.builtins_env.vars["None"] = NONE
        self.stack = []
        self.mode = []
        self.initialized = False
        self._dispatch = {}
        self.main_env = None
        main = loaded.main
        self.tests = [d for d in main.program.decls if isinstance(d, (N.TestDecl, N.PropertyDecl))] \
            if main and main.program else []

    # ---- setup -----------------------------------------------------------------
    def initialize(self):
        if self.initialized:
            return
        self.initialized = True
        for m in self.loaded.modules:
            env = Env(self.builtins_env)
            m.env = env
            for d in m.program.decls:
                if isinstance(d, N.FnDecl):
                    env.vars[d.name] = Closure(d.name, [p.name for p in d.params], d.body, env, decl=d)
            for item, (dep, kind) in m.import_from.items():
                if kind in ("fn", "const"):
                    env.vars[item] = dep.env.vars[item]
            for d in m.program.decls:
                if isinstance(d, N.ConstDecl):
                    self.stack = [(f"const {d.name}", d.span)]
                    env.vars[d.name] = self.eval(d.value, env)
                    self.stack = []
        self.main_env = self.loaded.main.env

    # ---- errors ----------------------------------------------------------------
    def error(self, code, msg, span, details=None, hint=None):
        return KlarRuntimeError(code, msg, span, details, list(self.stack), hint)

    def src(self, span):
        lines = self.sources.get(span.file)
        if not lines or span.line <= 0:
            return "?"
        if span.line != span.end_line:
            return lines[span.line - 1][span.col - 1:].strip() + " ..."
        return lines[span.line - 1][span.col - 1:span.end_col - 1]

    def names_in(self, expr, env):
        out, seen = [], set()
        for n in N.walk(expr):
            if isinstance(n, N.Name) and n.name not in seen:
                seen.add(n.name)
                try:
                    v = env.get(n.name)
                except KeyError:
                    continue
                if isinstance(v, (Closure, Builtin)) or (v is NONE and n.name == "None"):
                    continue
                out.append(f"{n.name} = {show(v, False)}")
        return out

    # ---- calls -----------------------------------------------------------------
    def call_value(self, fv, args, span):
        if isinstance(fv, Builtin):
            if self.prof is None:
                return fv.impl(self, args, span)
            self.prof.enter(f"<builtin> {fv.name}")
            try:
                return fv.impl(self, args, span)
            finally:
                self.prof.exit()
        if not isinstance(fv, Closure):
            raise self.error("R0099", f"internal: value is not callable: {show(fv)}", span)
        if len(self.stack) >= MAX_DEPTH:
            raise self.error("R0006", f"stack overflow: more than {MAX_DEPTH} nested calls (in `{fv.name}`)", span,
                             hint="check the base case of the recursion")
        env = Env(fv.env, dict(zip(fv.params, args)))
        self.stack.append((fv.name, span))
        self.mode.append("fn")
        prof = self.prof
        if prof is not None:
            d0 = fv.decl
            loc = f"{d0.span.file}:{d0.span.line}" if d0 is not None else f"{span.file}:{span.line}"
            prof.enter(f"{fv.name} ({loc})")
        try:
            d = fv.decl
            if d is not None and d.requires:
                for r in d.requires:
                    if not self.eval(r, env):
                        raise self.error("R0002", f"precondition `{self.src(r.span)}` of `{d.name}` violated",
                                         r.span, self.names_in(r, env),
                                         hint="the caller passed arguments that the function does not accept")
            try:
                if fv.expr_body:
                    result = self.eval(fv.body, env)
                else:
                    self.exec_block(fv.body, env)
                    result = UNIT
            except ReturnSignal as rs:
                result = rs.value
            if d is not None and d.ensures:
                env2 = Env(env, {"result": result})
                for en in d.ensures:
                    if not self.eval(en, env2):
                        raise self.error("R0003", f"postcondition `{self.src(en.span)}` of `{d.name}` violated",
                                         en.span, self.names_in(en, env2),
                                         hint="the function body returned a value that breaks its own contract")
            return result
        finally:
            self.stack.pop()
            self.mode.pop()
            if prof is not None:
                prof.exit()

    def order_args(self, names, args, env):
        if all(a.name is None for a in args):
            return [self.eval(a.value, env) for a in args]
        vals = {}
        pos = 0
        for a in args:
            v = self.eval(a.value, env)
            if a.name is None:
                vals[names[pos]] = v
                pos += 1
            else:
                vals[a.name] = v
        return [vals[n] for n in names]

    # ---- statements ------------------------------------------------------------
    def exec_block(self, block, env):
        inner = Env(env)
        ex = self.exec
        for s in block.stmts:
            ex(s, inner)

    def exec(self, s, env):
        if self.prof is not None:
            self.prof.line(s.span)
        t = type(s)
        if t is N.ExprStmt:
            self.eval(s.expr, env)
        elif t is N.Let:
            v = self.eval(s.value, env)
            if s.name != "_":
                env.vars[s.name] = v
        elif t is N.Assign:
            env.set(s.name, self.eval(s.value, env))
        elif t is N.Return:
            raise ReturnSignal(UNIT if s.value is None else self.eval(s.value, env))
        elif t is N.If:
            if self.eval(s.cond, env):
                self.exec_block(s.then, env)
            elif isinstance(s.else_, N.If):
                self.exec(s.else_, env)
            elif s.else_ is not None:
                self.exec_block(s.else_, env)
        elif t is N.While:
            while self.eval(s.cond, env):
                try:
                    self.exec_block(s.body, env)
                except BreakSignal:
                    break
                except ContinueSignal:
                    continue
        elif t is N.For:
            for x in self.eval(s.iter, env):
                inner = Env(env, {s.var: x})
                try:
                    self.exec_block(s.body, inner)
                except BreakSignal:
                    break
                except ContinueSignal:
                    continue
        elif t is N.Break:
            raise BreakSignal()
        elif t is N.Continue:
            raise ContinueSignal()
        elif t is N.Assert:
            self.exec_assert(s, env)
        else:
            raise self.error("R0099", f"internal: unknown statement {t.__name__}", s.span)

    def exec_assert(self, s, env):
        c = s.cond
        if isinstance(c, N.Binary) and c.op in ("==", "!=", "<", ">", "<=", ">="):
            left = self.eval(c.left, env)
            right = self.eval(c.right, env)
            okv = self.compare(c.op, left, right, c.span)
            details = [f"left = {show(left, False)}", f"right = {show(right, False)}"]
        else:
            okv = self.eval(c, env)
            details = self.names_in(c, env)
        if not okv:
            msg = f"assertion failed: `{self.src(c.span)}`"
            if s.message is not None:
                msg += f" — {self.eval(s.message, env)}"
            raise self.error("R0005", msg, s.span, details)

    # ---- expressions -----------------------------------------------------------
    def eval(self, e, env):
        fn = self._dispatch.get(type(e))
        if fn is None:
            fn = getattr(self, "ev_" + type(e).__name__)
            self._dispatch[type(e)] = fn
        return fn(e, env)

    def ev_IntLit(self, e, env):
        return e.value

    ev_FloatLit = ev_IntLit
    ev_BoolLit = ev_IntLit

    def ev_UnitLit(self, e, env):
        return UNIT

    def ev_StrLit(self, e, env):
        return "".join(p if isinstance(p, str) else show(self.eval(p, env), True) for p in e.parts)

    def ev_ListLit(self, e, env):
        return tuple(self.eval(x, env) for x in e.items)

    def ev_MapLit(self, e, env):
        return KMap({self.eval(en.key, env): self.eval(en.value, env) for en in e.entries})

    def ev_Name(self, e, env):
        try:
            return env.get(e.name)
        except KeyError:
            raise self.error("R0099", f"internal: unbound name `{e.name}`", e.span)

    def ev_Unary(self, e, env):
        v = self.eval(e.operand, env)
        if e.op == "not":
            return not v
        return -v

    def compare(self, op, a, b, span):
        if op == "==":
            return a == b
        if op == "!=":
            return a != b
        if op == "<":
            return a < b
        if op == ">":
            return a > b
        if op == "<=":
            return a <= b
        return a >= b

    def ev_Binary(self, e, env):
        op = e.op
        if op == "and":
            return bool(self.eval(e.left, env)) and bool(self.eval(e.right, env))
        if op == "or":
            return bool(self.eval(e.left, env)) or bool(self.eval(e.right, env))
        a = self.eval(e.left, env)
        b = self.eval(e.right, env)
        if op == "+":
            return a + b
        if op == "-":
            return a - b
        if op == "*":
            return a * b
        if op in ("/", "%"):
            if b == 0:
                raise self.error("R0001", f"division by zero in `{self.src(e.span)}`", e.span,
                                 self.names_in(e, env))
            if isinstance(a, float):
                return a / b if op == "/" else a - b * int(a / b)
            q = abs(a) // abs(b)
            if (a < 0) != (b < 0):
                q = -q
            return q if op == "/" else a - b * q
        return self.compare(op, a, b, e.span)

    def ev_Call(self, e, env):
        fv = self.eval(e.callee, env)
        if isinstance(fv, Closure):
            names = fv.params
        elif isinstance(fv, Builtin):
            names = fv.param_names
        else:
            raise self.error("R0099", "internal: call of non-function", e.span)
        return self.call_value(fv, self.order_args(names, e.args, env), e.span)

    def is_type_ref(self, obj, env):
        return isinstance(obj, N.Name) and not env.has(obj.name)

    def ev_MethodCall(self, e, env):
        obj = e.obj
        m = e.method
        if obj.__class__ is N.Name and obj.name in self.enums and not env.has(obj.name):
            fields = self.enums[obj.name][m]
            return Variant(obj.name, m, self.order_args(fields, e.args, env), fields)
        recv = self.eval(obj, env)
        if isinstance(recv, Record) and m in recv.fields and isinstance(recv.fields[m], (Closure, Builtin)):
            f = recv.fields[m]
            return self.call_value(f, [self.eval(a.value, env) for a in e.args], e.span)
        if m == "to_str" and not e.args:
            return show(recv, True)
        h = type_head(recv)
        entry = METHODS.get(h, {}).get(m)
        if entry is not None:
            sig, impl = entry
            args = self.order_args(param_names(sig, skip_self=True), e.args, env)
            if self.prof is None:
                return impl(self, [recv] + args, e.span)
            self.prof.enter(f"<builtin> {h}.{m}")
            try:
                return impl(self, [recv] + args, e.span)
            finally:
                self.prof.exit()
        try:
            fv = env.get(m)
        except KeyError:
            fv = None
        if isinstance(fv, Closure):
            args = self.order_args(fv.params[1:], e.args, env)
            return self.call_value(fv, [recv] + args, e.span)
        raise self.error("R0099", f"internal: no method `{m}` for {h}", e.span)

    def ev_FieldAccess(self, e, env):
        obj = e.obj
        if obj.__class__ is N.Name and obj.name in self.enums and not env.has(obj.name):
            return Variant(obj.name, e.name)
        return self.eval(obj, env).fields[e.name]

    def ev_Try(self, e, env):
        v = self.eval(e.expr, env)
        if v.name in ("Some", "Ok"):
            return v.values[0]
        if self.mode and self.mode[-1] == "test":
            raise self.error("R0008", f"`{self.src(e.expr.span)}?` produced {show(v, False)} inside a test",
                             e.span)
        raise ReturnSignal(v)

    def ev_RecordLit(self, e, env):
        given = {f.name: self.eval(f.value, env) for f in e.fields}
        return Record(e.type_name, {k: given[k] for k in self.records[e.type_name]})

    def ev_WithExpr(self, e, env):
        base = self.eval(e.base, env)
        fields = dict(base.fields)
        for f in e.fields:
            fields[f.name] = self.eval(f.value, env)
        return Record(base.type_name, fields)

    def ev_Lambda(self, e, env):
        return Closure("<lambda>", [p.name for p in e.params], e.body, env,
                       expr_body=not isinstance(e.body, N.Block))

    def ev_Match(self, e, env):
        v = self.eval(e.subject, env)
        for arm in e.arms:
            binds = {}
            if self.match(arm.pattern, v, binds):
                inner = Env(env, binds)
                if arm.guard is not None and not self.eval(arm.guard, inner):
                    continue
                if isinstance(arm.body, N.Block):
                    self.exec_block(arm.body, inner)
                    return UNIT
                return self.eval(arm.body, inner)
        raise self.error("R0099", f"internal: no match arm for {show(v, False)}", e.span)

    def match(self, p, v, binds):
        t = type(p)
        if t is N.PWild:
            return True
        if t is N.PBind:
            binds[p.name] = v
            return True
        if t is N.PLit:
            return type(v) is type(p.value) and v == p.value
        if t is N.PVariant:
            if not isinstance(v, Variant) or v.name != p.variant:
                return False
            if p.enum is not None and v.enum != p.enum:
                return False
            return all(self.match(sp, sv, binds) for sp, sv in zip(p.args, v.values))
        return False

    # ---- entry points ----------------------------------------------------------
    def run_main(self):
        self.initialize()
        main = self.main_env.vars["main"]
        self.mode = []
        result = self.call_value(main, [], main.decl.name_span)
        if isinstance(result, Variant) and result.enum == "Result" and result.name == "Err":
            raise KlarRuntimeError("R0007", f"main returned {show(result, False)}", main.decl.name_span)
        return result

    def run_test(self, t, runs=100, seed=0):
        self.initialize()
        if isinstance(t, N.PropertyDecl):
            return self.run_property(t, runs, seed)
        self.stack = [(f'test "{t.name}"', t.span)]
        self.mode = ["test"]
        try:
            self.exec_block(t.body, self.main_env)
        except ReturnSignal:
            pass
        finally:
            self.stack = []
            self.mode = []
        return None

    # ---- property-based testing --------------------------------------------------
    def try_property(self, d, args):
        self.stack = [(f'property "{d.name}"', d.span)]
        self.mode = ["test"]
        env = Env(self.main_env, {p.name: v for p, v in zip(d.params, args)})
        try:
            self.exec_block(d.body, env)
        except ReturnSignal:
            pass
        except KlarRuntimeError as ex:
            return ex
        finally:
            self.stack = []
            self.mode = []
        return None

    def run_property(self, d, runs, seed):
        rng = random.Random(f"{seed}:{d.name}")
        real_out = self.out
        self.out = io.StringIO()
        try:
            for i in range(runs):
                size = 1 + (i * 10) // max(runs, 1)
                args = [self.gen(t, rng, size, 0) for t in d.param_types]
                failure = self.try_property(d, args)
                if failure is not None:
                    args, failure = self.shrink(d, args, failure)
                    inputs = [f"{p.name} = {show(v, False)}" for p, v in zip(d.params, args)]
                    raise KlarRuntimeError(
                        "R0010", f"property falsified after {i + 1} run(s) (seed {seed}): {failure.message}",
                        failure.span, inputs + failure.details, failure.stack,
                        hint=f"minimal counterexample: {', '.join(inputs)}; reproduce with `--seed {seed}`")
        finally:
            self.out = real_out
        return runs

    def gen(self, t, rng, size, depth):
        t = prune(t)
        name = t.name if isinstance(t, TCon) else None
        if name == "Int":
            r = rng.random()
            if r < 0.3:
                return rng.choice([0, 1, -1, 2, -2, 10, -10, 100])
            if r < 0.35:
                return rng.randint(-10 ** 12, 10 ** 12)
            return rng.randint(-size * 10, size * 10)
        if name == "Float":
            if rng.random() < 0.25:
                return rng.choice([0.0, 1.0, -1.0, 0.5, -0.5])
            return round(rng.uniform(-size * 10, size * 10), 3)
        if name == "Bool":
            return rng.random() < 0.5
        if name == "Str":
            alphabet = "abcxyzAB01 -_é"
            return "".join(rng.choice(alphabet) for _ in range(rng.randint(0, size)))
        if name == "Unit":
            return UNIT
        if name == "List":
            return tuple(self.gen(t.args[0], rng, size, depth + 1) for _ in range(rng.randint(0, size)))
        if name == "Map":
            return KMap({self.gen(t.args[0], rng, size, depth + 1): self.gen(t.args[1], rng, size, depth + 1)
                         for _ in range(rng.randint(0, size))})
        if name == "Option":
            return NONE if rng.random() < 0.25 else some(self.gen(t.args[0], rng, size, depth + 1))
        if name == "Result":
            if rng.random() < 0.5:
                return ok(self.gen(t.args[0], rng, size, depth + 1))
            return err(self.gen(t.args[1], rng, size, depth + 1))
        uni = self.universe
        if name in uni.records:
            info = uni.records[name]
            m = dict(zip(info.tparams, t.args))
            return Record(name, {f: self.gen(subst(ft, m), rng, size, depth + 1) for f, ft in info.fields.items()})
        if name in uni.enums:
            info = uni.enums[name]
            m = dict(zip(info.tparams, t.args))
            variants = list(info.variants.items())
            if depth > 3:
                def recursive(fs):
                    return any(name in repr(ft) for _, ft in fs)
                flat = [v for v in variants if not recursive(v[1])]
                variants = flat or sorted(variants, key=lambda v: len(v[1]))[:1]
            vname, fs = rng.choice(variants)
            return Variant(name, vname, [self.gen(subst(ft, m), rng, size, depth + 1) for _, ft in fs],
                           [f for f, _ in fs])
        return UNIT

    def shrink(self, d, args, failure):
        best, best_err = list(args), failure
        attempts = 0
        improved = True
        while improved and attempts < 1000:
            improved = False
            for i in range(len(best)):
                for cand in self.shrink_value(best[i]):
                    attempts += 1
                    trial = best[:i] + [cand] + best[i + 1:]
                    e = self.try_property(d, trial)
                    if e is not None:
                        best, best_err, improved = trial, e, True
                        break
                    if attempts >= 1000:
                        break
                if improved or attempts >= 1000:
                    break
        return best, best_err

    def shrink_value(self, v):
        out = []
        if isinstance(v, bool):
            if v:
                out.append(False)
        elif isinstance(v, int):
            if v != 0:
                out += [0, int(v / 2), v - (1 if v > 0 else -1)]
        elif isinstance(v, float):
            if v != 0.0:
                out += [0.0, float(int(v)), v / 2]
        elif isinstance(v, str):
            if v:
                out += ["", v[:len(v) // 2], v[1:], v[:-1]]
        elif isinstance(v, tuple):
            if v:
                out += [(), v[:len(v) // 2], v[len(v) // 2:]]
                out += [v[:i] + v[i + 1:] for i in range(min(len(v), 8))]
                for i, x in enumerate(v[:8]):
                    out += [v[:i] + (c,) + v[i + 1:] for c in self.shrink_value(x)[:3]]
        elif isinstance(v, KMap):
            if v.d:
                out.append(KMap())
                for k in list(v.d)[:8]:
                    nd = dict(v.d)
                    del nd[k]
                    out.append(KMap(nd))
        elif isinstance(v, Variant):
            if v.enum == "Option" and v.name == "Some":
                out.append(NONE)
            for i, x in enumerate(v.values):
                for c in self.shrink_value(x)[:3]:
                    vals = list(v.values)
                    vals[i] = c
                    out.append(Variant(v.enum, v.name, vals, v.field_names))
            if v.enum not in ("Option", "Result"):
                # try simpler variants of recursive enums: any payload value of the same enum
                for x in v.values:
                    if isinstance(x, Variant) and x.enum == v.enum:
                        out.append(x)
        elif isinstance(v, Record):
            for k, x in v.fields.items():
                for c in self.shrink_value(x)[:3]:
                    nf = dict(v.fields)
                    nf[k] = c
                    out.append(Record(v.type_name, nf))
        return [c for c in out if c != v or type(c) is not type(v)]


def run_with_big_stack(fn):
    """Run fn in a thread with a large stack so deep Klar recursion works."""
    result = {}

    def target():
        try:
            result["value"] = fn()
        except BaseException as ex:  # noqa: BLE001 (propagated to the caller thread)
            result["error"] = ex

    old_limit = sys.getrecursionlimit()
    sys.setrecursionlimit(max(old_limit, 400000))
    try:
        threading.stack_size(512 * 1024 * 1024)
    except (ValueError, RuntimeError):
        threading.stack_size(64 * 1024 * 1024)
    th = threading.Thread(target=target)
    th.start()
    th.join()
    threading.stack_size(0)
    sys.setrecursionlimit(old_limit)
    if "error" in result:
        raise result["error"]
    return result.get("value")
