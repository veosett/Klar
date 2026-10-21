"""Compile-time safety analysis (runs after type checking, before any backend).

Klar follows the Rust idea: whatever can be ruled out before the program runs is rejected
by the compiler, with a precise message and a fix. This pass removes whole classes of
run-time failures:

  E0701  Int division / remainder by a value that is not proven non-zero
         (Float division only when the divisor is certainly 0.0)
  E0702  unconditional recursion (every path calls the function again -> stack overflow)
  E0703  a call whose constant arguments violate the callee's `requires`
  E0704  a constant argument outside a built-in's domain (negative `pow` exponent, `sqrt(-1.0)`, ...)
  E0705  a list index that is out of bounds on every call (`xs.get(xs.len())`, negative index)
  E0215  sorting / min / max of values that have no order

Non-zero proofs use a small sign analysis (each value is a subset of {-, 0, +}) with facts
learned from conditions (`if b != 0`, `while b > 0`, `requires n > 0`, `assert`, early
`return`, `match b { 0 => ..., _ => ... }`, `if xs.is_empty() { return ... }`, callee
`ensures result > 0`) and summaries of `var` updates (`var d = 3 ... d = d + 2` stays > 0).
"""
from . import nodes as N
from .diagnostics import Diagnostic, Span
from .types import TCon, TFn, TParam, head, prune

NEG, ZERO, POS = "-", "0", "+"
ANY = frozenset("-0+")
NONZERO = frozenset("-+")
NONNEG = frozenset("0+")
NONPOS = frozenset("-0")
S_POS, S_NEG, S_ZERO = frozenset("+"), frozenset("-"), frozenset("0")

_ADD = {("+", "+"): "+", ("+", "0"): "+", ("0", "+"): "+", ("0", "0"): "0", ("-", "-"): "-",
        ("-", "0"): "-", ("0", "-"): "-"}
_MUL = {("+", "+"): "+", ("-", "-"): "+", ("+", "-"): "-", ("-", "+"): "-"}
FLIP = {"+": "-", "-": "+", "0": "0"}
SWAP = {"<": ">", ">": "<", "<=": ">=", ">=": "<=", "==": "==", "!=": "!="}
NEGATE = {"<": ">=", ">=": "<", ">": "<=", "<=": ">", "==": "!=", "!=": "=="}
ORDERED = ("Int", "Float", "Str")


def sign_of_number(v):
    return S_POS if v > 0 else S_NEG if v < 0 else S_ZERO


def s_add(a, b):
    out = set()
    for x in a:
        for y in b:
            r = _ADD.get((x, y))
            out |= {r} if r else set(ANY)
    return frozenset(out)


def s_neg(a):
    return frozenset(FLIP[x] for x in a)


def s_mul(a, b):
    out = set()
    for x in a:
        for y in b:
            out.add("0" if "0" in (x, y) else _MUL[(x, y)])
    return frozenset(out)


def s_div(a, b):
    out = set()
    for x in a:
        for y in b:
            if x == "0":
                out.add("0")
            elif y == "0":
                out |= ANY
            else:
                out |= {"0", _MUL[(x, y)]}
    return frozenset(out)


def s_mod(a, b):
    out = set()
    for x in a:
        out |= {"0"} if x == "0" else {"0", x}
    return frozenset(out)


def tname(t):
    t = prune(t) if t is not None else None
    return head(t) if isinstance(t, TCon) else None


class NotConst(Exception):
    pass


class Safety:
    def __init__(self, checker, program):
        self.checker = checker
        self.program = program
        self.diags = []
        self.consts = {}
        self.const_signs = {}
        self.fn_decls = {}
        for name, sig in checker.fns.items():
            decl = getattr(sig, "decl", None)
            if isinstance(decl, N.FnDecl):
                self.fn_decls[name] = decl

    def error(self, code, msg, span, hint=None, fix=None, notes=None):
        self.diags.append(Diagnostic(code, "error", msg, span, hint, fix, notes or []))

    # ---- driver ------------------------------------------------------------------------
    def run(self):
        for d in self.program.decls:
            if isinstance(d, N.ConstDecl):
                try:
                    self.consts[d.name] = self.const_value(d.value, {})
                    if isinstance(self.consts[d.name], (int, float)) and not isinstance(self.consts[d.name], bool):
                        self.const_signs[d.name] = sign_of_number(self.consts[d.name])
                except NotConst:
                    pass
        for d in self.program.decls:
            if isinstance(d, N.FnDecl):
                self.function(d)
                self.check_recursion(d)
            elif isinstance(d, (N.TestDecl, N.PropertyDecl)):
                self.begin(None, [p.name for p in getattr(d, "params", [])])
                self.walk(d.body.stmts, {})
        return self.diags

    def begin(self, decl, params):
        self.decl = decl
        self.params = set(params)
        self.vars = {}          # var name -> (init expr, [assigned exprs])
        self.lets = {}          # let name -> value expr
        self.loopvars = {}      # for-loop variable -> sign
        self.var_init = {}      # var name -> sign of its initial value (with the facts at the declaration)
        self.memo = {}
        self.computing = set()

    def function(self, d):
        self.begin(d, [p.name for p in d.params])
        self.collect(d.body)
        facts = {}
        for r in d.requires:
            self.assume(r, True, facts)
        self.walk(d.body.stmts, facts)

    # ---- declarations inside a body (flow-insensitive summaries) -------------------------
    def collect(self, node):
        for n in iter_nodes(node):
            if isinstance(n, N.Let):
                if n.mutable:
                    self.vars.setdefault(n.name, [n.value, []])[0] = n.value
                else:
                    self.lets[n.name] = n.value
            elif isinstance(n, N.Assign):
                self.vars.setdefault(n.name, [None, []])[1].append(n.value)

    def summary(self, name, override=None):
        if name in self.computing:
            return ANY
        init, assigns = self.vars[name]
        if init is None:
            return ANY
        self.computing.add(name)
        try:
            cur = self.var_init[name] if name in self.var_init else self.sign_of(init, {})
            for _ in range(4):
                nxt = cur
                for rhs in assigns:
                    nxt = nxt | self.sign_of(rhs, {}, {name: cur})
                if nxt == cur:
                    break
                cur = nxt
            return cur
        finally:
            self.computing.discard(name)

    # ---- signs ------------------------------------------------------------------------------
    def sign_of(self, e, facts, override=None):
        k = keyof(e)
        if k is not None and k in facts:
            return facts[k][0]
        if isinstance(e, N.IntLit):
            return sign_of_number(e.value)
        if isinstance(e, N.FloatLit):
            return sign_of_number(e.value)
        if isinstance(e, N.Name):
            n = e.name
            if override and n in override:
                return override[n]
            if n in self.loopvars:
                return self.loopvars[n]
            if n in self.vars:
                if override is None and n in self.memo:
                    return self.memo[n]
                s = self.summary(n)
                if override is None:
                    self.memo[n] = s
                return s
            if n in self.lets:
                if n in self.computing:
                    return ANY
                self.computing.add(n)
                try:
                    return self.sign_of(self.lets[n], {}, override)
                finally:
                    self.computing.discard(n)
            if n in self.const_signs:
                return self.const_signs[n]
            return ANY
        if isinstance(e, N.Unary) and e.op == "-":
            return s_neg(self.sign_of(e.operand, facts, override))
        if isinstance(e, N.Binary) and e.op in ("+", "-", "*", "/", "%") and tname(getattr(e, "kt", None)) in \
                ("Int", "Float"):
            a = self.sign_of(e.left, facts, override)
            b = self.sign_of(e.right, facts, override)
            if e.op == "+":
                return s_add(a, b)
            if e.op == "-":
                return s_add(a, s_neg(b))
            if e.op == "*":
                return s_mul(a, b)
            if e.op == "/":
                return s_div(a, b)
            return s_mod(a, b)
        if isinstance(e, N.MethodCall) and getattr(e, "resolved", (None,))[0] == "builtin":
            m = e.method
            recv = self.sign_of(e.obj, facts, override)
            if m in ("len", "count") and not e.args:
                return NONNEG
            if m == "abs":
                return S_POS if "0" not in recv else NONNEG
            if m == "to_float":
                return recv
            if m == "max" and e.args:
                other = self.sign_of(e.args[0].value, facts, override)
                if recv <= S_POS or other <= S_POS:
                    return S_POS
                if recv <= NONNEG or other <= NONNEG:
                    return NONNEG
            return ANY
        if isinstance(e, N.Call) and isinstance(e.callee, N.Name) and e.callee.name in self.fn_decls:
            callee = self.fn_decls[e.callee.name]
            if callee.ensures:
                fx = {}
                for en in callee.ensures:
                    self.assume(en, True, fx)
                if "result" in fx:
                    return fx["result"][0]
        return ANY

    # ---- facts from conditions -----------------------------------------------------------------
    def refine(self, x, s, facts):
        k = keyof(x)
        if k is None:
            return
        cur = self.sign_of(x, facts)
        new = cur & s
        facts[k] = (new if new else s, vars_of(x))

    def assume(self, c, truth, facts):
        if isinstance(c, N.Binary) and c.op == "and":
            if truth:
                self.assume(c.left, True, facts)
                self.assume(c.right, True, facts)
            return
        if isinstance(c, N.Binary) and c.op == "or":
            if not truth:
                self.assume(c.left, False, facts)
                self.assume(c.right, False, facts)
            return
        if isinstance(c, N.Unary) and c.op == "not":
            self.assume(c.operand, not truth, facts)
            return
        if isinstance(c, N.MethodCall) and c.method == "is_empty" and not c.args:
            k = keyof(c.obj)
            if k is not None:
                facts[k + ".len()"] = (S_ZERO if truth else S_POS, vars_of(c.obj))
            return
        if isinstance(c, N.Binary) and c.op in SWAP:
            op = c.op if truth else NEGATE[c.op]
            self.compare_fact(c.left, op, c.right, facts)
            self.compare_fact(c.right, SWAP[op], c.left, facts)

    def compare_fact(self, x, op, y, facts):
        """Learn the sign of x from `x op y` being true."""
        if keyof(x) is None:
            return
        sy = self.sign_of(y, facts)
        if op == "==":
            self.refine(x, sy, facts)
        elif op == "!=" and sy == S_ZERO:
            self.refine(x, NONZERO, facts)
        elif op == ">" and sy <= NONNEG:
            self.refine(x, S_POS, facts)
        elif op == ">=" and sy <= S_POS:
            self.refine(x, S_POS, facts)
        elif op == ">=" and sy <= NONNEG:
            self.refine(x, NONNEG, facts)
        elif op == "<" and sy <= NONPOS:
            self.refine(x, S_NEG, facts)
        elif op == "<=" and sy <= S_NEG:
            self.refine(x, S_NEG, facts)
        elif op == "<=" and sy <= NONPOS:
            self.refine(x, NONPOS, facts)

    # ---- statements -------------------------------------------------------------------------
    def walk(self, stmts, facts):
        """Returns (facts after the statements, whether they always leave the block)."""
        for s in stmts:
            facts, exits = self.stmt(s, facts)
            if exits:
                return facts, True
        return facts, False

    def block(self, b, facts):
        if b is None:
            return dict(facts), False
        if isinstance(b, N.If):
            return self.stmt(b, dict(facts))
        return self.walk(b.stmts, dict(facts))

    def stmt(self, s, facts):
        if isinstance(s, N.Let):
            self.expr(s.value, facts)
            if s.mutable:
                self.var_init[s.name] = self.sign_of(s.value, facts)
            return facts, False
        if isinstance(s, N.Assign):
            self.expr(s.value, facts)
            sign = self.sign_of(s.value, facts)
            after = invalidate(facts, {s.name})
            after[s.name] = (sign, {s.name})      # until the next assignment, the variable has this sign
            return after, False
        if isinstance(s, N.Return):
            if s.value is not None:
                self.expr(s.value, facts)
            return facts, True
        if isinstance(s, (N.Break, N.Continue)):
            return facts, True
        if isinstance(s, N.Assert):
            self.expr(s.cond, facts)
            if s.message is not None:
                self.expr(s.message, facts)
            self.assume(s.cond, True, facts)
            return facts, False
        if isinstance(s, N.ExprStmt):
            self.expr(s.expr, facts)
            e = s.expr
            never = isinstance(e, N.Call) and isinstance(e.callee, N.Name) and e.callee.name in ("fail", "todo")
            return facts, never
        if isinstance(s, N.If):
            self.expr(s.cond, facts)
            tf = dict(facts)
            self.assume(s.cond, True, tf)
            ef = dict(facts)
            self.assume(s.cond, False, ef)
            t_after, t_exit = self.block(s.then, tf)
            e_after, e_exit = self.block(s.else_, ef)
            if t_exit and e_exit:
                return facts, True
            if t_exit:
                return e_after, False
            if e_exit:
                return t_after, False
            return invalidate(facts, assigned_in(s.then) | assigned_in(s.else_)), False
        if isinstance(s, N.While):
            loop = invalidate(facts, assigned_in(s.body))
            self.expr(s.cond, loop)
            bf = dict(loop)
            self.assume(s.cond, True, bf)
            self.walk(s.body.stmts, bf)
            after = dict(loop)
            if not has_break(s.body):
                self.assume(s.cond, False, after)
            return after, False
        if isinstance(s, N.For):
            self.expr(s.iter, facts)
            sign = ANY
            it = s.iter
            if isinstance(it, N.Call) and isinstance(it.callee, N.Name) and it.callee.name == "range" and it.args:
                lo = self.sign_of(it.args[0].value, facts)
                sign = S_POS if lo <= S_POS else NONNEG if lo <= NONNEG else ANY
            self.loopvars[s.var] = sign
            loop = invalidate(facts, assigned_in(s.body))
            self.walk(s.body.stmts, dict(loop))
            return loop, False
        return facts, False

    # ---- expressions ---------------------------------------------------------------------------
    def expr(self, e, facts):
        if e is None or not isinstance(e, N.Node):
            return
        if isinstance(e, N.Binary):
            if e.op in ("and", "or"):
                self.expr(e.left, facts)
                rf = dict(facts)
                self.assume(e.left, e.op == "and", rf)
                self.expr(e.right, rf)
                return
            self.expr(e.left, facts)
            self.expr(e.right, facts)
            if e.op in ("/", "%"):
                self.check_divisor(e, facts)
            return
        if isinstance(e, N.Match):
            self.expr(e.subject, facts)
            k = keyof(e.subject)
            excluded_zero = False
            for arm in e.arms:
                af = dict(facts)
                if k is not None and excluded_zero:
                    self.refine(e.subject, NONZERO, af)
                if isinstance(arm.pattern, N.PBind):
                    self.lets[arm.pattern.name] = e.subject
                    if k is not None and k in af:
                        af[arm.pattern.name] = (af[k][0], set())
                if arm.guard is not None:
                    self.expr(arm.guard, af)
                    self.assume(arm.guard, True, af)
                if isinstance(arm.body, N.Block):
                    self.walk(arm.body.stmts, af)
                else:
                    self.expr(arm.body, af)
                if arm.guard is None and isinstance(arm.pattern, N.PLit) and arm.pattern.value in (0, 0.0) and \
                        not isinstance(arm.pattern.value, bool):
                    excluded_zero = True
            return
        if isinstance(e, N.Lambda):
            lf = {k: v for k, v in facts.items() if not (v[1] & set(self.vars))}
            if isinstance(e.body, N.Block):
                self.walk(e.body.stmts, lf)
            else:
                self.expr(e.body, lf)
            return
        if isinstance(e, N.Call):
            for a in e.args:
                self.expr(a.value, facts)
            self.expr(e.callee, facts)
            self.check_contract(e)
            return
        if isinstance(e, N.MethodCall):
            self.expr(e.obj, facts)
            for a in e.args:
                self.expr(a.value, facts)
            self.check_builtin(e, facts)
            return
        for child in children(e):
            self.expr(child, facts)

    # ---- the checks ------------------------------------------------------------------------------
    def check_divisor(self, e, facts):
        kind = tname(getattr(e.left, "kt", None))
        if kind not in ("Int", "Float"):
            return
        s = self.sign_of(e.right, facts)
        try:
            if self.const_value(e.right, {}) == 0:
                s = S_ZERO
        except NotConst:
            pass
        what = "division" if e.op == "/" else "remainder"
        text = source_text(e.right)
        if s == S_ZERO:
            self.error("E0701", f"{what} by zero: `{text}` is always 0", e.right.span,
                       hint="the result would be a run-time error (R0001); fix the divisor")
            return
        if kind == "Int" and "0" in s:
            hint = (f"prove the divisor is not zero first: `if {text} != 0 {{ ... }}`, "
                    f"`match {text} {{ 0 => ..., _ => ... }}`, an early `if {text} == 0 {{ return ... }}`")
            fix = None
            if isinstance(e.right, N.Name) and e.right.name in self.params and self.decl is not None:
                hint += f", or make it the caller's job: `requires {text} != 0`"
                se = self.decl.effects_span or self.decl.sig_end
                fix = {"span": Span(se.file, se.end_line, se.end_col, se.end_line, se.end_col),
                       "text": f" requires {text} != 0", "safe": False}
            self.error("E0701", f"{what} by `{text}`, which may be zero", e.right.span, hint=hint, fix=fix,
                       notes=["Klar rejects Int division that could fail at run time; "
                              "the compiler accepts literals, checked values, `requires` and `var`s that stay non-zero"])

    def check_builtin(self, e, facts):
        if getattr(e, "resolved", (None,))[0] != "builtin":
            return
        recv_t = tname(getattr(e.obj, "kt", None))
        m = e.method
        args = [a.value for a in e.args]
        if recv_t == "List" and m in ("sort", "min", "max", "sort_by", "min_by", "max_by"):
            if m in ("sort", "min", "max"):
                t = prune(e.obj.kt)
                elem = prune(t.args[0]) if isinstance(t, TCon) and t.args else None
            else:
                ft = prune(getattr(args[0], "kt", None)) if args else None
                elem = prune(ft.ret) if isinstance(ft, TFn) else None
            if elem is not None and not (isinstance(elem, TCon) and elem.name in ORDERED and not elem.args):
                shown = elem.name if isinstance(elem, (TCon, TParam)) else str(elem)
                self.error("E0215", f"`{m}` needs ordered values, but the {'elements' if m in ('sort', 'min', 'max') else 'keys'} "
                                    f"have type `{shown}`", e.method_span,
                           hint="only Int, Float and Str are ordered; use `sort_by(fn(x) => x.some_field)` "
                                "with an Int/Float/Str key")
            return
        if recv_t == "List" and m in ("get", "set", "insert", "remove_at") and args:
            idx = args[0]
            k = keyof(e.obj)
            always_out = (k is not None and keyof(idx) == k + ".len()" and m != "insert") or \
                self.sign_of(idx, facts) <= S_NEG
            if always_out:
                result = "is always `None`" if m == "get" else "always fails (R0011)"
                self.error("E0705", f"index `{source_text(idx)}` is out of bounds on every call: "
                                    f"`.{m}` {result}", idx.span,
                           hint=f"indexes go from 0 to `{source_text(e.obj)}.len() - 1`; the last element is "
                                f"`{source_text(e.obj)}.last()`")
                return
        bad = None
        if recv_t == "Int" and m == "pow" and args and self.sign_of(args[0], facts) <= S_NEG:
            bad = "`Int.pow` needs a non-negative exponent (use Float for fractions)"
        elif recv_t == "Float" and m == "sqrt" and self.sign_of(e.obj, facts) <= S_NEG:
            bad = "`sqrt` of a negative number"
        elif recv_t == "Float" and m == "ln" and self.sign_of(e.obj, facts) <= NONPOS:
            bad = "`ln` needs a positive number"
        elif recv_t == "List" and m == "chunks" and args and self.sign_of(args[0], facts) <= NONPOS:
            bad = "`chunks` needs a positive size"
        elif recv_t == "Float" and m == "fixed" and args and self.sign_of(args[0], facts) <= S_NEG:
            bad = "`fixed` needs a non-negative number of digits"
        elif recv_t == "Str" and m == "count" and args and isinstance(args[0], N.StrLit) and args[0].parts in ([], [""]):
            bad = "`count` of the empty string"
        if bad:
            self.error("E0704", f"invalid argument: {bad}", e.span,
                       hint="the call would always fail at run time (R0009)")

    def check_contract(self, e):
        if not isinstance(e.callee, N.Name) or e.callee.name not in self.fn_decls:
            return
        callee = self.fn_decls[e.callee.name]
        if not callee.requires:
            return
        env = {}
        positional = [a for a in e.args if a.name is None]
        for p, a in zip(callee.params, positional):
            env[p.name] = a.value
        for a in e.args:
            if a.name is not None:
                env[a.name] = a.value
        values = {}
        for name, ex in env.items():
            try:
                values[name] = self.const_value(ex, {})
            except NotConst:
                pass
        for r in callee.requires:
            try:
                ok = self.const_value(r, values)
            except NotConst:
                continue
            if ok is False:
                shown = ", ".join(f"{k} = {show_value(v)}" for k, v in values.items() if k in names_in(r))
                self.error("E0703", f"this call always violates `requires {source_text(r)}` of `{callee.name}`",
                           e.span, hint="pass arguments that satisfy the precondition",
                           notes=[f"values: {shown}"] if shown else None)
                return

    # ---- unconditional recursion -----------------------------------------------------------------
    def check_recursion(self, d):
        name = d.name

        found = []

        def calls_self(e):
            """Does evaluating e certainly call `name` (ignoring lambdas / lazy branches)?"""
            if e is None or not isinstance(e, N.Node):
                return False
            if isinstance(e, N.Call):
                if isinstance(e.callee, N.Name) and e.callee.name == name:
                    found.append(e)
                    return True
                return any(calls_self(a.value) for a in e.args)
            if isinstance(e, N.MethodCall):
                res = getattr(e, "resolved", None)
                if res and res[0] == "ufcs" and res[2] == name:
                    found.append(e)
                    return True
                return calls_self(e.obj) or any(calls_self(a.value) for a in e.args)
            if isinstance(e, N.Binary) and e.op in ("and", "or"):
                return calls_self(e.left)
            if isinstance(e, (N.Lambda,)):
                return False
            if isinstance(e, N.Match):
                return calls_self(e.subject)
            return any(calls_self(c) for c in children(e))

        for s in d.body.stmts:
            if isinstance(s, N.Let) and calls_self(s.value) or \
                    isinstance(s, N.Assign) and calls_self(s.value) or \
                    isinstance(s, N.Return) and calls_self(s.value) or \
                    isinstance(s, N.ExprStmt) and calls_self(s.expr) or \
                    isinstance(s, (N.If, N.While)) and calls_self(s.cond) or \
                    isinstance(s, N.Assert) and calls_self(s.cond):
                self.error("E0702", f"`{name}` calls itself on every path: the recursion never ends",
                           found[0].span if found else d.name_span,
                           hint=f"add a base case at the start of `{name}` that returns without calling it "
                                f"(e.g. `if n <= 1 {{ return 1 }}`)",
                           notes=["at run time this would be a stack overflow (R0006)"])
                return
            if isinstance(s, (N.Return, N.If, N.While, N.For, N.Break, N.Continue)) or \
                    isinstance(s, N.ExprStmt) and isinstance(s.expr, N.Match):
                return

    # ---- constant evaluation -----------------------------------------------------------------------
    def const_value(self, e, env):
        if isinstance(e, (N.IntLit, N.FloatLit, N.BoolLit)):
            return e.value
        if isinstance(e, N.StrLit):
            if all(isinstance(p, str) for p in e.parts):
                return "".join(e.parts)
            raise NotConst()
        if isinstance(e, N.Name):
            if e.name in env:
                return env[e.name]
            if e.name in self.consts:
                return self.consts[e.name]
            raise NotConst()
        if isinstance(e, N.Unary):
            v = self.const_value(e.operand, env)
            if e.op == "-" and isinstance(v, (int, float)) and not isinstance(v, bool):
                return -v
            if e.op == "not" and isinstance(v, bool):
                return not v
            raise NotConst()
        if isinstance(e, N.Binary):
            if e.op in ("and", "or"):
                a = self.const_value(e.left, env)
                if e.op == "and" and a is False:
                    return False
                if e.op == "or" and a is True:
                    return True
                return self.const_value(e.right, env)
            a = self.const_value(e.left, env)
            b = self.const_value(e.right, env)
            if type(a) is not type(b):
                raise NotConst()
            op = e.op
            if op == "==":
                return a == b
            if op == "!=":
                return a != b
            if op in ("<", ">", "<=", ">=") and not isinstance(a, bool):
                return {"<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}[op]
            if isinstance(a, bool):
                raise NotConst()
            if op == "+":
                return a + b
            if op == "-" and not isinstance(a, str):
                return a - b
            if op == "*" and not isinstance(a, str):
                return a * b
            if op in ("/", "%") and not isinstance(a, str):
                if b == 0:
                    raise NotConst()
                if isinstance(a, float):
                    return a / b if op == "/" else a - b * int(a / b)
                q = abs(a) // abs(b)
                q = q if (a < 0) == (b < 0) else -q
                return q if op == "/" else a - b * q
            raise NotConst()
        if isinstance(e, N.MethodCall) and not e.args:
            v = self.const_value(e.obj, env)
            if e.method == "len" and isinstance(v, str):
                return len(v)
            if e.method == "abs" and isinstance(v, (int, float)) and not isinstance(v, bool):
                return abs(v)
        raise NotConst()


# ---- AST helpers -------------------------------------------------------------------------------------
def children(e):
    out = []
    for name in getattr(e, "__dataclass_fields__", {}):
        if name == "span" or name.endswith("_span"):
            continue
        v = getattr(e, name)
        if isinstance(v, N.Node):
            out.append(v)
        elif isinstance(v, list):
            for x in v:
                if isinstance(x, N.Node):
                    out.append(x)
    if isinstance(e, N.Arg):
        return [e.value]
    if isinstance(e, (N.FieldInit, N.MapEntry)):
        return [c for c in out]
    return out


def iter_nodes(n):
    stack = [n]
    while stack:
        x = stack.pop()
        if isinstance(x, N.Node):
            yield x
            stack.extend(children(x))


def keyof(e):
    if isinstance(e, N.Name):
        return e.name
    if isinstance(e, N.FieldAccess):
        k = keyof(e.obj)
        return None if k is None else f"{k}.{e.name}"
    if isinstance(e, N.MethodCall) and not e.args and getattr(e, "resolved", (None,))[0] == "builtin":
        k = keyof(e.obj)
        return None if k is None else f"{k}.{e.method}()"
    return None


def vars_of(e):
    if isinstance(e, N.Name):
        return {e.name}
    if isinstance(e, (N.FieldAccess, N.MethodCall)):
        return vars_of(e.obj)
    return set()


def names_in(e):
    return {n.name for n in iter_nodes(e) if isinstance(n, N.Name)}


def invalidate(facts, names):
    if not names:
        return dict(facts)
    return {k: v for k, v in facts.items() if not (v[1] & names) and k not in names}


def assigned_in(node):
    if node is None:
        return set()
    return {n.name for n in iter_nodes(node) if isinstance(n, N.Assign)}


def has_break(body):
    def walk(n):
        if isinstance(n, N.Break):
            return True
        if isinstance(n, (N.While, N.For, N.Lambda)):
            return False
        return any(walk(c) for c in children(n))
    return any(walk(s) for s in body.stmts)


def source_text(e):
    if isinstance(e, N.Name):
        return e.name
    if isinstance(e, N.IntLit):
        return str(e.value)
    if isinstance(e, N.FloatLit):
        return repr(e.value)
    if isinstance(e, N.FieldAccess):
        return f"{source_text(e.obj)}.{e.name}"
    if isinstance(e, N.MethodCall):
        return f"{source_text(e.obj)}.{e.method}({', '.join(source_text(a.value) for a in e.args)})"
    if isinstance(e, N.Call) and isinstance(e.callee, N.Name):
        return f"{e.callee.name}({', '.join(source_text(a.value) for a in e.args)})"
    if isinstance(e, N.Binary):
        return f"{source_text(e.left)} {e.op} {source_text(e.right)}"
    if isinstance(e, N.Unary):
        return f"{e.op}{' ' if e.op == 'not' else ''}{source_text(e.operand)}"
    if isinstance(e, N.BoolLit):
        return "true" if e.value else "false"
    if isinstance(e, N.StrLit) and all(isinstance(p, str) for p in e.parts):
        return '"' + "".join(e.parts) + '"'
    return "..."


def show_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return '"' + v + '"'
    return str(v)


def analyze(checker, program):
    return Safety(checker, program).run()
