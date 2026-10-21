"""Semantic checker: names, types, effects, exhaustiveness, AI-oriented lints.

One Checker checks one module. Type declarations live in a shared Universe
(type names are unique per program); functions and constants are per module
and cross module borders only through explicit `use m.{name}` imports.
"""
import difflib
import re

from . import nodes as N
from .builtins import GLOBALS, METHODS, FOREIGN_METHODS, FOREIGN_NOTES, parsed
from .diagnostics import Diagnostic, Span
from .types import (ANY, BOOL, FLOAT, INT, NEVER, STR, UNIT, TCon, TFn, TParam, TVar,
                    head, is_unit, list_of, map_of, option_of, prune, result_of, show, subst, unify)

KNOWN_EFFECTS = {"io", "time", "rand", "fs", "net"}
PRIMS = {"Int", "Float", "Bool", "Str", "Unit", "Never"}
GENERIC_ARITY = {"List": 1, "Map": 2, "Option": 1, "Result": 2}
PASCAL = re.compile(r"^[A-Z][A-Za-z0-9]*$")
SNAKE = re.compile(r"^_?[a-z][a-z0-9_]*$|^_$")
UPPER = re.compile(r"^[A-Z][A-Z0-9_]*$")


class Sig:
    def __init__(self, name, tparams, params, ret, effects, decl=None, user=False, module=None):
        self.name = name
        self.tparams = tparams
        self.params = params        # list of (name, Type)
        self.ret = ret
        self.effects = set(effects)
        self.decl = decl
        self.user = user
        self.module = module


class RecordInfo:
    def __init__(self, name, tparams, module, span):
        self.name, self.tparams, self.module, self.span = name, tparams, module, span
        self.fields = {}


class EnumInfo:
    def __init__(self, name, tparams, module, span):
        self.name, self.tparams, self.module, self.span = name, tparams, module, span
        self.variants = {}


class AliasInfo:
    def __init__(self, name, tparams, target, module, span):
        self.name, self.tparams, self.target, self.module, self.span = name, tparams, target, module, span
        self.resolving = False


class Universe:
    """Program-wide registry of type declarations."""

    def __init__(self):
        self.records = {}
        self.enums = {}
        self.aliases = {}

    def owner(self, name):
        for table in (self.records, self.enums, self.aliases):
            if name in table:
                return table[name].module
        return None


class Var:
    __slots__ = ("type", "mutable", "span", "used", "kind", "decl_kw_span")

    def __init__(self, type_, mutable, span, kind, decl_kw_span=None):
        self.type = type_
        self.mutable = mutable
        self.span = span
        self.used = False
        self.kind = kind
        self.decl_kw_span = decl_kw_span


class Ctx:
    def __init__(self, name, ret, effects, is_test=False, sig_end=None, purpose="fn"):
        self.name = name
        self.ret = ret
        self.effects = set(effects)
        self.is_test = is_test
        self.loop = 0
        self.sig_end = sig_end
        self.purpose = purpose  # fn | lambda | test | contract | const


def _resolve_builtin_type(te, tps):
    if isinstance(te, N.FnTypeExpr):
        return TFn([_resolve_builtin_type(p, tps) for p in te.params], _resolve_builtin_type(te.ret, tps))
    if te.name in tps:
        return tps[te.name]
    if te.name == "Never":
        return NEVER
    return TCon(te.name, [_resolve_builtin_type(a, tps) for a in te.args])


def _builtin_sig(sig_text):
    d = parsed(sig_text)
    tps = {t: TParam(t) for t in d.type_params}
    params = [(p.name, _resolve_builtin_type(p.type, tps)) for p in d.params]
    ret = _resolve_builtin_type(d.ret, tps) if d.ret else UNIT
    return Sig(d.name, d.type_params, params, ret, d.effects)


BUILTIN_GLOBALS = {name: _builtin_sig(s) for name, (s, _) in GLOBALS.items()}
_SYS_GLOBALS = None


def sys_globals():
    global _SYS_GLOBALS
    if _SYS_GLOBALS is None:
        from .native.intrinsics import SYS_SIGNATURES
        _SYS_GLOBALS = {}
        for text in SYS_SIGNATURES:
            sig = _builtin_sig(text)
            _SYS_GLOBALS[sig.name] = sig
    return _SYS_GLOBALS
BUILTIN_METHODS = {owner: {name: _builtin_sig(s) for name, (s, _) in ms.items()} for owner, ms in METHODS.items()}


def suggest(name, candidates):
    m = difflib.get_close_matches(name, list(candidates), n=1, cutoff=0.6)
    return m[0] if m else None


class Checker:
    def __init__(self, program: N.Program, file: str, universe=None, imports=None, module=None, sys=False):
        self.sys = sys
        self.globals = dict(BUILTIN_GLOBALS)
        if sys:
            self.globals.update(sys_globals())
        self.program = program
        self.file = file
        self.module = module or file
        self.universe = universe or Universe()
        self.records = self.universe.records
        self.enums = self.universe.enums
        self.aliases = self.universe.aliases
        self.diags = []
        self.fns = {}          # name -> Sig (own + imported)
        self.consts = {}       # name -> Type (own + imported)
        self.own_consts = []   # declaration order
        self.visible = set()   # type names this module may write
        self.imported = set()
        self.scopes = []
        self.ctx = None
        self.tparams = {}
        self.const_allowed = None
        for name, (kind, value) in (imports or {}).items():
            self.imported.add(name)
            if kind == "fn":
                self.fns[name] = value
            elif kind == "const":
                self.consts[name] = value
            elif kind == "type":
                self.visible.add(name)

    # ---- reporting -----------------------------------------------------------
    def error(self, code, msg, span, hint=None, fix=None, notes=None):
        self.diags.append(Diagnostic(code, "error", msg, span, hint, fix, notes or []))

    def warn(self, code, msg, span, hint=None, fix=None):
        self.diags.append(Diagnostic(code, "warning", msg, span, hint, fix))

    def did_you_mean(self, name, candidates, span):
        s = suggest(name, candidates)
        if s:
            return f"did you mean `{s}`?", {"span": span, "text": s, "safe": False}
        return None, None

    # ---- entry ---------------------------------------------------------------
    def run(self):
        self.collect()
        for d in self.program.decls:
            if isinstance(d, N.ConstDecl):
                self.check_const(d)
        for d in self.program.decls:
            if isinstance(d, N.FnDecl):
                self.check_fn(d)
            elif isinstance(d, N.TestDecl):
                self.check_test(d)
            elif isinstance(d, N.PropertyDecl):
                self.check_property(d)
        if "main" in self.fns and "main" not in self.imported:
            sig = self.fns["main"]
            ret = prune(sig.ret)
            ok_ret = is_unit(ret) or (head(ret) == "Result" and is_unit(ret.args[0]))
            if sig.params or not ok_ret:
                self.error("E0502", "`main` must take no parameters and return `Unit` or `Result[Unit, E]`",
                           sig.decl.name_span)
        self.diags.sort(key=lambda d: (d.span.file != self.file, d.span.line, d.span.col))
        return self.diags

    # ---- declarations --------------------------------------------------------
    def type_names_visible(self):
        return self.visible | PRIMS | set(GENERIC_ARITY)

    def collect(self):
        test_names = set()
        own_types = []
        for d in self.program.decls:
            if isinstance(d, (N.TypeDecl, N.EnumDecl, N.AliasDecl)):
                if not PASCAL.match(d.name):
                    fixed = d.name[:1].upper() + re.sub(r"_(\w)", lambda m: m.group(1).upper(), d.name[1:])
                    self.error("E0103", f"type name `{d.name}` must be PascalCase", d.span,
                               hint=f"rename it to `{fixed}`")
                for t in d.type_params:
                    if not PASCAL.match(t):
                        self.error("E0103", f"type parameter `{t}` must be PascalCase (e.g. `T`)", d.span)
                owner = self.universe.owner(d.name)
                if owner is not None or d.name in PRIMS or d.name in GENERIC_ARITY:
                    where = " (built-in)" if owner is None else (f" in module `{owner}`" if owner != self.module else "")
                    hint = "type names are unique across the whole program; pick another name" if owner not in (None, self.module) else None
                    self.error("E0101", f"type `{d.name}` is already defined{where}", d.span, hint=hint)
                    continue
                if isinstance(d, N.TypeDecl):
                    self.records[d.name] = RecordInfo(d.name, d.type_params, self.module, d.span)
                elif isinstance(d, N.EnumDecl):
                    self.enums[d.name] = EnumInfo(d.name, d.type_params, self.module, d.span)
                else:
                    self.aliases[d.name] = AliasInfo(d.name, d.type_params, d.target, self.module, d.span)
                self.visible.add(d.name)
                own_types.append(d)
            elif isinstance(d, N.FnDecl):
                if d.name in self.fns or d.name in self.globals or d.name in self.consts:
                    what = ("a built-in function" if d.name in self.globals else
                            "imported" if d.name in self.imported else "already defined")
                    self.error("E0101", f"function `{d.name}` is {what}", d.name_span)
                    continue
                if not SNAKE.match(d.name):
                    self.warn("W0104", f"function name `{d.name}` should be snake_case", d.name_span,
                              hint=f"rename it to `{to_snake(d.name)}`")
                self.fns[d.name] = None  # placeholder
            elif isinstance(d, N.ConstDecl):
                if not UPPER.match(d.name):
                    self.error("E0103", f"constant `{d.name}` must be UPPER_SNAKE_CASE", d.name_span,
                               hint=f"rename it to `{to_snake(d.name).upper()}`")
                if d.name in self.consts or d.name in self.fns:
                    self.error("E0101", f"`{d.name}` is already defined", d.name_span)
                    continue
                self.consts[d.name] = None
                self.own_consts.append(d)
            elif isinstance(d, (N.TestDecl, N.PropertyDecl)):
                if d.name in test_names:
                    self.error("E0101", f"duplicate test name \"{d.name}\"", d.span)
                test_names.add(d.name)
        # resolve type declarations (all names are registered now, so recursion works)
        for d in own_types:
            tps = {t: TParam(t) for t in d.type_params}
            if isinstance(d, N.TypeDecl):
                info = self.records[d.name]
                for f in d.fields:
                    if f.name in info.fields:
                        self.error("E0101", f"duplicate field `{f.name}` in `{d.name}`", f.span)
                    info.fields[f.name] = self.resolve(f.type, tps)
            elif isinstance(d, N.EnumDecl):
                info = self.enums[d.name]
                for v in d.variants:
                    if not PASCAL.match(v.name):
                        self.error("E0103", f"variant name `{v.name}` must be PascalCase", v.span)
                    if v.name in info.variants:
                        self.error("E0101", f"duplicate variant `{v.name}` in `{d.name}`", v.span)
                    info.variants[v.name] = [(f.name, self.resolve(f.type, tps)) for f in v.fields]
                if not info.variants:
                    self.error("E0302", f"enum `{d.name}` has no variants", d.span)
            else:
                self.resolve(N.TypeName(span=d.span, name=d.name, args=[
                    N.TypeName(span=d.span, name=t, args=[]) for t in d.type_params]), tps)
        for d in self.own_consts:
            self.consts[d.name] = self.resolve(d.type, {})
        for d in self.program.decls:
            if isinstance(d, N.FnDecl) and self.fns.get(d.name, 0) is None:
                tps = {t: TParam(t) for t in d.type_params}
                for t in d.type_params:
                    if not PASCAL.match(t):
                        self.error("E0103", f"type parameter `{t}` must be PascalCase (e.g. `T`)", d.name_span)
                params = []
                seen = set()
                for p in d.params:
                    if p.name in seen:
                        self.error("E0101", f"duplicate parameter `{p.name}`", p.span)
                    seen.add(p.name)
                    params.append((p.name, self.resolve(p.type, tps)))
                ret = self.resolve(d.ret, tps) if d.ret else UNIT
                for e in d.effects:
                    if e not in KNOWN_EFFECTS:
                        h, fx = self.did_you_mean(e, KNOWN_EFFECTS, d.effects_span)
                        self.error("E0403", f"unknown effect `{e}`", d.effects_span,
                                   hint=h or "known effects: io, time, rand, fs, net")
                self.fns[d.name] = Sig(d.name, d.type_params, params, ret, d.effects, decl=d, user=True,
                                       module=self.module)

    def not_imported(self, name, span):
        owner = self.universe.owner(name)
        self.error("E0104", f"type `{name}` is defined in module `{owner}` but not imported here", span,
                   hint=f"add `use {owner}.{{{name}}}` at the top of the file")

    def resolve(self, te, tps):
        if te is None:
            return ANY
        if isinstance(te, N.FnTypeExpr):
            return TFn([self.resolve(p, tps) for p in te.params], self.resolve(te.ret, tps))
        name = te.name
        if name in tps:
            if te.args:
                self.error("E0105", f"type parameter `{name}` takes no type arguments", te.span)
            return tps[name]
        if name in PRIMS or (name == "Word" and self.sys):
            if te.args:
                self.error("E0105", f"`{name}` takes no type arguments", te.span)
            return NEVER if name == "Never" else TCon(name)
        if name in GENERIC_ARITY:
            n = GENERIC_ARITY[name]
            if len(te.args) != n:
                example = {"List": "List[Int]", "Option": "Option[Str]", "Map": "Map[Str, Int]",
                           "Result": "Result[Int, Str]"}[name]
                self.error("E0105", f"`{name}` takes {n} type argument(s), got {len(te.args)}", te.span,
                           hint=f"for example `{example}`")
                return TCon(name, [ANY] * n)
            return TCon(name, [self.resolve(a, tps) for a in te.args])
        info = self.records.get(name) or self.enums.get(name) or self.aliases.get(name)
        if info is not None:
            if name not in self.visible:
                self.not_imported(name, te.span)
            args = [self.resolve(a, tps) for a in te.args]
            if len(args) != len(info.tparams):
                if info.tparams:
                    ex = f"{name}[{', '.join(info.tparams)}]"
                    self.error("E0105", f"`{name}` takes {len(info.tparams)} type argument(s), got {len(args)}",
                               te.span, hint=f"write `{ex}` with concrete types, e.g. `{name}[{', '.join('Int' for _ in info.tparams)}]`")
                else:
                    self.error("E0105", f"`{name}` is not generic", te.span)
                args = (args + [ANY] * len(info.tparams))[:len(info.tparams)]
            if isinstance(info, AliasInfo):
                if info.resolving:
                    self.error("E0104", f"type alias `{name}` refers to itself", te.span,
                               hint="recursive types must be `enum` or `type` records, not aliases")
                    return ANY
                info.resolving = True
                saved_visible = self.visible
                try:
                    if info.module != self.module:
                        # resolve in the alias's own module context: its names are allowed there
                        self.visible = self.visible | set(self.records) | set(self.enums) | set(self.aliases)
                    return self.resolve(info.target, dict(zip(info.tparams, args)))
                finally:
                    info.resolving = False
                    self.visible = saved_visible
            return TCon(name, args)
        aliases = {"int": "Int", "integer": "Int", "i32": "Int", "i64": "Int", "number": "Int", "float": "Float",
                   "f64": "Float", "double": "Float", "bool": "Bool", "boolean": "Bool", "string": "Str",
                   "String": "Str", "str": "Str", "void": "Unit", "None": "Unit", "Vec": "List", "Array": "List",
                   "list": "List", "dict": "Map", "HashMap": "Map", "Dict": "Map", "Optional": "Option",
                   "Maybe": "Option", "Either": "Result", "Tuple": "Pair"}
        cands = self.type_names_visible() | set(tps)
        if name in aliases:
            hint, fix = f"Klar calls this type `{aliases[name]}`", {"span": te.span, "text": aliases[name]}
        else:
            hint, fix = self.did_you_mean(name, cands, te.span)
        self.error("E0104", f"unknown type `{name}`", te.span, hint=hint, fix=fix)
        return ANY

    # ---- generic type helpers --------------------------------------------------
    def fresh(self, info):
        """A fresh instance `Name[?A, ?B]` and its parameter mapping."""
        mapping = {t: TVar(t) for t in info.tparams}
        return TCon(info.name, [mapping[t] for t in info.tparams]), mapping

    def args_map(self, info, t):
        t = prune(t)
        if isinstance(t, TCon) and len(t.args) == len(info.tparams):
            return dict(zip(info.tparams, t.args))
        return {tp: ANY for tp in info.tparams}

    def check_type_visible(self, name, span):
        if name not in self.visible:
            self.not_imported(name, span)

    # ---- scopes --------------------------------------------------------------
    def push(self):
        self.scopes.append({})

    def pop(self):
        sc = self.scopes.pop()
        for name, v in sc.items():
            if not v.used and not name.startswith("_") and v.kind in ("let", "var", "param", "for", "bind"):
                what = {"param": "parameter", "for": "loop variable", "bind": "pattern variable"}.get(v.kind, "variable")
                self.warn("W0402", f"unused {what} `{name}`", v.span,
                          hint=f"remove it or rename it to `_{name}`")

    def lookup(self, name):
        for sc in reversed(self.scopes):
            if name in sc:
                return sc[name]
        return None

    def declare(self, name, t, mutable, span, kind, kw_span=None):
        if name == "_":
            return
        prev = self.lookup(name)
        if prev is not None or name in self.fns or name in self.globals or name in self.consts:
            if prev is not None:
                where = f" (first declared at {prev.span.short()})"
            elif name in self.consts:
                where = " (a constant has this name)"
            else:
                where = " (a function has this name)"
            hint = f"choose a new descriptive name (e.g. `{name}_2`)"
            if prev is not None and prev.kind in ("let", "var"):
                hint += ", or declare the original with `var` and reassign it"
            self.error("E0102", f"`{name}` is already defined{where}; Klar forbids shadowing", span, hint=hint)
        elif not SNAKE.match(name):
            self.warn("W0104", f"variable `{name}` should be snake_case", span,
                      hint=f"rename it to `{to_snake(name)}`")
        self.scopes[-1][name] = Var(t, mutable, span, kind, kw_span)

    # ---- functions, constants & tests --------------------------------------------
    def check_const(self, d: N.ConstDecl):
        t = self.consts.get(d.name)
        if t is None:
            return
        self.tparams = {}
        self.scopes = [{}]
        self.ctx = Ctx(f"const {d.name}", t, set(), purpose="const")
        idx = self.own_consts.index(d)
        self.const_allowed = {c.name for c in self.own_consts[:idx]}
        self.expr(d.value, t)
        self.const_allowed = None
        self.ctx = None

    def check_fn(self, d: N.FnDecl):
        sig = self.fns.get(d.name)
        if sig is None or sig.decl is not d:
            return
        self.tparams = {t: TParam(t) for t in d.type_params}
        self.scopes = []
        self.push()
        for (pname, pt), p in zip(sig.params, d.params):
            self.declare(pname, pt, False, p.span, "param")
        # contracts are pure and see the parameters (+ `result` in ensures)
        self.ctx = Ctx(d.name, sig.ret, set(), purpose="contract")
        for r in d.requires:
            self.expr(r, BOOL)
        if d.ensures:
            self.push()
            self.scopes[-1]["result"] = Var(sig.ret, False, d.name_span, "builtin")
            for e in d.ensures:
                self.expr(e, BOOL)
            self.scopes.pop()
        self.ctx = Ctx(d.name, sig.ret, (KNOWN_EFFECTS | {"sys"}) if self.sys else sig.effects, sig_end=d.sig_end)
        self.block(d.body)
        ret = prune(sig.ret)
        if not is_unit(ret) and ret is not NEVER and ret is not ANY and not self.returns(d.body):
            self.error("E0205", f"function `{d.name}` may reach its end without returning `{show(ret)}`",
                       d.name_span, hint="add `return <value>` at the end of every path (Klar has no implicit returns)")
        self.pop()
        self.ctx = None

    def check_test(self, d: N.TestDecl):
        self.tparams = {}
        self.scopes = []
        self.push()
        self.ctx = Ctx(f'test "{d.name}"', UNIT, {"io"}, is_test=True, purpose="test")
        self.block(d.body)
        self.pop()
        self.ctx = None

    def check_property(self, d: N.PropertyDecl):
        self.tparams = {}
        self.scopes = []
        self.push()
        d.param_types = []
        for p in d.params:
            t = self.resolve(p.type, {})
            if not self.generatable(t, set()):
                self.error("E0605", f"cannot generate random values of type `{show(t)}` for property input `{p.name}`",
                           p.span, hint="property inputs may be Int, Float, Bool, Str, Unit, List, Map, Option, "
                                        "Result and records/enums built from them")
            d.param_types.append(t)
            self.declare(p.name, t, False, p.span, "param")
        self.ctx = Ctx(f'property "{d.name}"', UNIT, {"io"}, is_test=True, purpose="test")
        self.block(d.body)
        self.pop()
        self.ctx = None

    def generatable(self, t, seen):
        t = prune(t)
        if isinstance(t, TFn) or t is ANY or isinstance(t, (TVar, TParam)) or t is NEVER:
            return False
        if not isinstance(t, TCon):
            return False
        if t.name in PRIMS or t.name in GENERIC_ARITY:
            return all(self.generatable(a, seen) for a in t.args)
        if t.name in seen:
            return True
        info = self.records.get(t.name) or self.enums.get(t.name)
        if info is None:
            return False
        m = self.args_map(info, t)
        seen = seen | {t.name}
        if isinstance(info, RecordInfo):
            return all(self.generatable(subst(ft, m), seen) for ft in info.fields.values())
        return all(self.generatable(subst(ft, m), seen) for fs in info.variants.values() for _, ft in fs)

    # ---- statements ----------------------------------------------------------
    def block(self, b: N.Block):
        self.push()
        for s in b.stmts:
            self.stmt(s)
        self.pop()

    def stmt(self, s):
        m = getattr(self, "s_" + type(s).__name__)
        m(s)

    def s_Let(self, s: N.Let):
        if s.type is not None:
            t = self.resolve(s.type, self.tparams)
            self.expr(s.value, t)
        else:
            t = self.expr(s.value)
        if prune(t) is NEVER and s.name != "_":
            t = ANY
        s.kt = t
        self.declare(s.name, t, s.mutable, s.name_span, "var" if s.mutable else "let", s.kw_span)

    def s_Assign(self, s: N.Assign):
        v = self.lookup(s.name)
        if v is None:
            if s.name in self.fns:
                self.error("E0207", f"cannot assign to function `{s.name}`", s.span)
            elif s.name in self.consts:
                self.error("E0207", f"cannot assign to constant `{s.name}`", s.span,
                           hint=f"copy it into a variable: `var value = {s.name}`")
            else:
                self.error("E0201", f"unknown variable `{s.name}`", s.span,
                           hint=f"declare it first: `var {s.name} = ...`")
            self.expr(s.value)
            return
        if not v.mutable:
            fix = {"span": v.decl_kw_span, "text": "var"} if v.decl_kw_span else None
            kind = {"param": "parameter", "for": "loop variable", "bind": "pattern variable",
                    "builtin": "contract variable"}.get(v.kind, "immutable variable")
            self.error("E0207", f"cannot assign to {kind} `{s.name}` (declared with `let`)" if v.kind == "let"
                       else f"cannot assign to {kind} `{s.name}`", s.span,
                       hint="declare it with `var` instead of `let`" if v.kind == "let"
                       else f"copy it into a new variable: `var {s.name}_2 = {s.name}`",
                       fix=fix)
        self.expr(s.value, v.type)

    def s_Return(self, s: N.Return):
        ret = self.ctx.ret
        if s.value is None:
            r = prune(ret)
            if not is_unit(r) and not isinstance(r, TVar) and r is not ANY:
                self.error("E0202", f"`return` without a value in a function returning `{show(r)}`", s.span,
                           hint=f"write `return <{show(r)} value>`")
            elif isinstance(r, TVar):
                unify(r, UNIT)
        else:
            self.expr(s.value, ret)

    def s_If(self, s: N.If):
        self.expr(s.cond, BOOL)
        self.block(s.then)
        if isinstance(s.else_, N.If):
            self.s_If(s.else_)
        elif s.else_ is not None:
            self.block(s.else_)

    def s_While(self, s: N.While):
        self.expr(s.cond, BOOL)
        self.ctx.loop += 1
        self.block(s.body)
        self.ctx.loop -= 1

    def s_For(self, s: N.For):
        it = prune(self.expr(s.iter))
        elem = ANY
        if head(it) == "List":
            elem = it.args[0]
        elif isinstance(it, TVar):
            elem = TVar()
            unify(it, list_of(elem))
        elif it is not ANY:
            hint = {"Map": "iterate over `m.keys()`, `m.values()` or `m.entries()`", "Str": "iterate over `s.chars()`",
                    "Int": "iterate over `range(0, n)`"}.get(head(it), "only `List[T]` can be iterated")
            self.error("E0202", f"cannot iterate over `{show(it)}`", s.iter.span, hint=hint)
        s.elem_kt = elem
        self.push()
        self.declare(s.var, elem, False, s.var_span, "for")
        self.ctx.loop += 1
        self.block(s.body)
        self.ctx.loop -= 1
        self.pop()

    def s_Break(self, s):
        if self.ctx.loop == 0:
            self.error("E0213", "`break` outside of a loop", s.span)

    def s_Continue(self, s):
        if self.ctx.loop == 0:
            self.error("E0213", "`continue` outside of a loop", s.span)

    def s_Assert(self, s: N.Assert):
        self.expr(s.cond, BOOL)
        if s.message is not None:
            self.expr(s.message, STR)

    def s_ExprStmt(self, s: N.ExprStmt):
        e = s.expr
        t = prune(self.expr(e))
        if isinstance(t, TVar) or t is ANY or t is NEVER or is_unit(t):
            return
        if isinstance(e, (N.MethodCall, N.WithExpr)):
            recv = e.obj if isinstance(e, N.MethodCall) else e.base
            name = e.method if isinstance(e, N.MethodCall) else "with"
            if name in ("push", "set", "concat", "remove", "with", "reverse", "sort", "sort_by", "filter",
                        "map", "take", "drop", "replace", "upper", "lower", "trim", "insert", "remove_at",
                        "update", "merge", "unique", "map_values"):
                target = recv.name if isinstance(recv, N.Name) else "x"
                self.error("E0405", f"the result of `.{name}` is discarded — values are immutable, "
                                    f"so `{target}` is NOT modified",
                           e.span, hint=f"assign the new value: `{target} = <this expression>` (declare `var {target}`)",
                           fix={"span": Span(e.span.file, e.span.line, e.span.col, e.span.line, e.span.col),
                                "text": f"{target} = "} if isinstance(recv, N.Name) else None)
                return
        if head(t) == "Result":
            self.error("E0402", f"this `{show(t)}` is ignored; errors must be handled", e.span,
                       hint="propagate with `?`, handle with `match`, or discard explicitly with `let _ = ...`")
            return
        if isinstance(e, N.Call) and isinstance(e.callee, N.Name) and e.callee.name == "dbg":
            return
        self.warn("W0401", f"unused value of type `{show(t)}`", e.span,
                  hint="use `let _ = ...` to discard it explicitly")

    # ---- control-flow analysis -----------------------------------------------
    def returns(self, b) -> bool:
        return any(self.stmt_returns(s) for s in b.stmts)

    def stmt_returns(self, s) -> bool:
        if isinstance(s, N.Return):
            return True
        if isinstance(s, N.If):
            if s.else_ is None:
                return False
            other = self.stmt_returns(s.else_) if isinstance(s.else_, N.If) else self.returns(s.else_)
            return self.returns(s.then) and other
        if isinstance(s, N.ExprStmt):
            return self.diverges(s.expr)
        if isinstance(s, N.While):
            return isinstance(s.cond, N.BoolLit) and s.cond.value and not self.has_break(s.body)
        return False

    def diverges(self, e) -> bool:
        if isinstance(e, N.Call) and isinstance(e.callee, N.Name) and e.callee.name in ("fail", "todo"):
            return True
        if isinstance(e, N.Match):
            return all(self.returns(a.body) if isinstance(a.body, N.Block) else self.diverges(a.body)
                       for a in e.arms)
        return False

    def has_break(self, node) -> bool:
        for n in N.walk(node):
            if isinstance(n, N.Break):
                return True
        return False

    # ---- expressions ---------------------------------------------------------
    def expr(self, e, expected=None):
        t = getattr(self, "e_" + type(e).__name__)(e, expected)
        if expected is not None and not unify(expected, t):
            self.mismatch(expected, t, e.span)
            return expected
        e.kt = t  # static type (may contain type variables until the module is fully checked)
        return t

    def mismatch(self, expected, found, span, what=None):
        ex, fo = prune(expected), prune(found)
        hint, fix = None, None
        he, hf = head(ex), head(fo)
        if he == "Float" and hf == "Int":
            hint = "Klar has no implicit conversions: use a float literal (`1.0`) or `.to_float()`"
        elif he == "Int" and hf == "Float":
            hint = "convert explicitly with `.round()`, `.floor()`, `.ceil()` or `.to_int()`"
        elif he == "Str" and hf in ("Int", "Float", "Bool"):
            hint = "convert with `.to_str()` or use interpolation: \"{value}\""
        elif he == "Option" and unify(ex.args[0], fo):
            hint = "wrap the value: `Some(value)`"
        elif he == "Result" and unify(ex.args[0], fo):
            hint = "wrap the value: `Ok(value)`"
        elif hf == "Option" and unify(ex, fo.args[0]):
            hint = "the value may be missing: use `?`, `match`, or `.unwrap_or(default)`"
        elif hf == "Result" and unify(ex, fo.args[0]):
            hint = "the value may be an error: use `?`, `match`, or `.unwrap_or(default)`"
        msg = f"expected `{show(ex)}`, found `{show(fo)}`"
        if what:
            msg = f"{what}: {msg}"
        self.error("E0202", msg, span, hint=hint, fix=fix)

    def e_IntLit(self, e, exp):
        if self.sys and exp is not None and head(prune(exp)) == "Word":
            return TCon("Word")
        return INT

    def e_FloatLit(self, e, exp):
        return FLOAT

    def e_BoolLit(self, e, exp):
        return BOOL

    def e_UnitLit(self, e, exp):
        return UNIT

    def e_StrLit(self, e, exp):
        for p in e.parts:
            if not isinstance(p, str):
                t = prune(self.expr(p))
                if isinstance(t, TFn):
                    self.error("E0202", "cannot interpolate a function into a string", p.span)
        return STR

    def e_ListLit(self, e, exp):
        ex = prune(exp) if exp is not None else None
        elem = ex.args[0] if head(ex) == "List" else TVar()
        for it in e.items:
            self.expr(it, elem)
        return list_of(elem)

    def e_MapLit(self, e, exp):
        ex = prune(exp) if exp is not None else None
        if head(ex) == "Map":
            k, v = ex.args
        else:
            k, v = TVar(), TVar()
        for en in e.entries:
            kt = prune(self.expr(en.key, k))
            if head(kt) not in (None, "Int", "Str", "Bool") and not isinstance(kt, TVar):
                self.error("E0202", f"map keys must be `Int`, `Str` or `Bool`, found `{show(kt)}`", en.key.span)
            self.expr(en.value, v)
        return map_of(k, v)

    def visible_names(self):
        names = set(self.fns) | set(self.globals) | {"None"} | set(self.consts)
        for sc in self.scopes:
            names |= set(sc)
        return names

    def record_hint(self, name):
        fields = ", ".join(f"{f}: ..." for f in self.records[name].fields)
        return f"construct a value with `{name} {{ {fields} }}`"

    def e_Name(self, e, exp):
        v = self.lookup(e.name)
        if v is not None:
            v.used = True
            return v.type
        if e.name == "None":
            return option_of(TVar())
        if e.name in self.consts:
            if self.const_allowed is not None and e.name not in self.const_allowed and e.name not in self.imported:
                self.error("E0604", f"constant `{e.name}` is used before it is declared", e.span,
                           hint="constants may only refer to constants declared above them")
            return self.consts[e.name] or ANY
        sig = self.fns.get(e.name) or self.globals.get(e.name)
        if sig is not None:
            self.check_effects(sig, e.span)
            mapping = {t: TVar() for t in sig.tparams}
            e.sig, e.inst = sig, mapping
            return TFn([subst(t, mapping) for _, t in sig.params], subst(sig.ret, mapping))
        if e.name in self.records:
            self.error("E0201", f"`{e.name}` is a type, not a value", e.span, hint=self.record_hint(e.name))
            return ANY
        if e.name in self.enums:
            vs = ", ".join(f"`{e.name}.{v}`" for v in self.enums[e.name].variants)
            self.error("E0201", f"`{e.name}` is an enum type, not a value", e.span, hint=f"use a variant: {vs}")
            return ANY
        foreign = {"null": "None", "nil": "None", "True": "true", "False": "false", "self": None, "this": None,
                   "Math": None}
        if e.name in foreign:
            rep = foreign[e.name]
            if e.name == "Math":
                hint = "math functions are methods: `x.sqrt()`, `x.pow(2.0)`, `x.abs()`; constants `PI`, `E`"
            else:
                hint = f"write `{rep}`" if rep else "Klar has no methods with `self`; pass the value as the first parameter"
            fix = {"span": e.span, "text": rep} if rep else None
        else:
            hint, fix = self.did_you_mean(e.name, self.visible_names(), e.span)
        self.error("E0201", f"unknown name `{e.name}`", e.span, hint=hint, fix=fix)
        return ANY

    def e_Unary(self, e, exp):
        if e.op == "not":
            self.expr(e.operand, BOOL)
            return BOOL
        t = prune(self.expr(e.operand))
        if head(t) in ("Int", "Float", "Word") or t is ANY:
            return t
        if isinstance(t, TVar):
            unify(t, INT)
            return INT
        self.error("E0211", f"unary `-` is not defined for `{show(t)}`", e.span)
        return ANY

    def e_Binary(self, e, exp):
        op = e.op
        if op in ("and", "or"):
            self.expr(e.left, BOOL)
            self.expr(e.right, BOOL)
            return BOOL
        if self.sys and (is_lit(e.left) or is_lit(e.right)):
            word = TCon("Word")
            want_word = exp is not None and head(prune(exp)) == "Word"
            if is_lit(e.left) and not is_lit(e.right):
                rt = prune(self.expr(e.right))
                lt = prune(self.expr(e.left, word if head(rt) == "Word" else None))
            elif is_lit(e.right) and not is_lit(e.left):
                lt = prune(self.expr(e.left))
                rt = prune(self.expr(e.right, word if head(lt) == "Word" else None))
            else:
                lt = prune(self.expr(e.left, word if want_word else None))
                rt = prune(self.expr(e.right, word if want_word else None))
        else:
            lt = prune(self.expr(e.left))
            rt = prune(self.expr(e.right, lt if (self.sys and head(lt) == "Word") else None))
        num_hint = None
        if {head(lt), head(rt)} == {"Int", "Float"}:
            num_hint = "Klar has no implicit conversions: use `.to_float()` on the Int side, or `.round()` on the Float side"
        if op in ("==", "!="):
            if not unify(lt, rt):
                self.error("E0211", f"cannot compare `{show(lt)}` with `{show(rt)}`", e.span, hint=num_hint)
            elif isinstance(prune(lt), TFn):
                self.error("E0211", "functions cannot be compared", e.span)
            return BOOL
        if op in ("<", ">", "<=", ">="):
            if not unify(lt, rt):
                self.error("E0211", f"cannot compare `{show(lt)}` with `{show(rt)}`", e.span, hint=num_hint)
                return BOOL
            t = prune(lt)
            if head(t) not in ("Int", "Float", "Str", "Word") and not isinstance(t, TVar) and t is not ANY:
                self.error("E0211", f"`{op}` is not defined for `{show(t)}`", e.span,
                           hint="only Int, Float and Str are ordered")
            return BOOL
        # arithmetic
        if not unify(lt, rt):
            hint = num_hint
            if op == "+" and "Str" in (head(lt), head(rt)):
                hint = "use interpolation: \"{a}{b}\", or convert with `.to_str()`"
            for side, st in ((e.left, lt), (e.right, rt)):
                if head(st) in ("Option", "Result"):
                    what = "may be missing (`None`)" if head(st) == "Option" else "may be an error (`Err`)"
                    hint = (f"`{show(st)}` {what}: handle it first — `match x {{ Some(v) => ..., None => ... }}`, "
                            f"`x?`, or `x.unwrap_or(default)`") if head(st) == "Option" else \
                        (f"`{show(st)}` {what}: handle it first — `match x {{ Ok(v) => ..., Err(e) => ... }}`, "
                         f"`x?`, or `x.unwrap_or(default)`")
                    break
            self.error("E0211", f"cannot apply `{op}` to `{show(lt)}` and `{show(rt)}`", e.span, hint=hint)
            return ANY
        t = prune(lt)
        h = head(t)
        e.ty = h
        if h in ("Int", "Float", "Word"):
            return t
        if h == "Str" and op == "+":
            return STR
        if isinstance(t, TVar):
            unify(t, INT)
            return INT
        if t is ANY:
            return ANY
        hint = None
        if h == "List" and op == "+":
            hint = "use `.concat(other)` to join lists"
        elif h == "Str":
            hint = "strings support only `+`; use `.repeat(n)` for repetition"
        self.error("E0211", f"operator `{op}` is not defined for `{show(t)}`", e.span, hint=hint)
        return ANY

    # ---- calls -----------------------------------------------------------------
    def check_effects(self, sig, span):
        missing = sig.effects - self.ctx.effects
        if not missing:
            return
        effs = ", ".join(sorted(missing))
        purpose = self.ctx.purpose
        if purpose in ("contract", "const"):
            what = "contracts" if purpose == "contract" else "constants"
            self.error("E0401", f"{what} must be pure, but `{sig.name}` uses `{effs}`", span)
        elif purpose == "test" or self.ctx.is_test:
            self.error("E0401", f"tests may only use `io`, but `{sig.name}` uses `{effs}`", span,
                       hint="pass the time/random/file value as a parameter so the code under test stays deterministic")
        else:
            fix = None
            allowed = sorted(self.ctx.effects | missing)
            if self.ctx.sig_end is not None and not self.ctx.effects:
                se = self.ctx.sig_end
                fix = {"span": Span(se.file, se.end_line, se.end_col, se.end_line, se.end_col),
                       "text": " uses " + ", ".join(allowed)}
            self.error("E0401", f"calling `{sig.name}` requires effect `{effs}`, but `{self.ctx.name}` "
                                f"does not declare it", span,
                       hint=f"add `uses {', '.join(allowed)}` to the signature of `{self.ctx.name}`", fix=fix)

    def call_sig(self, sig, args, span, expected=None, self_type=None, display=None, node=None):
        display = display or sig.name
        mapping = {t: TVar(t) for t in sig.tparams}
        if node is not None:
            node.sig, node.inst = sig, mapping
        params = [(n, subst(t, mapping)) for n, t in sig.params]
        ret = subst(sig.ret, mapping)
        if self_type is not None:
            if not params or not unify(params[0][1], self_type):
                need = show(params[0][1]) if params else "?"
                self.error("E0204", f"method `{display}` needs a receiver of type `{need}`, found `{show(self_type)}`",
                           span)
                for a in args:
                    self.expr(a.value)
                return ANY
            params = params[1:]
        if expected is not None:
            unify(ret, expected)  # guides inference (e.g. Ok(1) with an expected error type)
        self.check_effects(sig, span)
        positional = [a for a in args if a.name is None]
        named = [a for a in args if a.name is not None]
        if positional and named and args.index(positional[-1]) > args.index(named[0]):
            self.error("E0209", "positional arguments must come before named ones", span)
        if sig.user and len(sig.params) >= 3 and positional and not self.sys:
            names = [n for n, _ in params]
            example = ", ".join(f"{n}: ..." for n in names)
            edits = [{"span": Span(a.span.file, a.span.line, a.span.col, a.span.line, a.span.col),
                      "text": f"{names[i]}: "} for i, a in enumerate(positional) if i < len(names)]
            self.error("E0208", f"`{display}` has {len(sig.params)} parameters, so arguments must be named",
                       span, hint=f"write `{display}({example})`", fix={"edits": edits} if edits else None)
        assigned = {}
        names = [n for n, _ in params]
        for i, a in enumerate(positional):
            if i < len(params):
                assigned[params[i][0]] = a
        if len(positional) > len(params):
            self.error("E0206", f"`{display}` takes {len(params)} argument(s) but {len(args)} were given", span)
            for a in positional[len(params):]:
                self.expr(a.value)
        for a in named:
            if a.name not in names:
                h, fx = self.did_you_mean(a.name, names, a.span)
                self.error("E0209", f"`{display}` has no parameter named `{a.name}`", a.span,
                           hint=h or f"parameters: {', '.join(names) or '(none)'}")
                self.expr(a.value)
            elif a.name in assigned:
                self.error("E0209", f"argument `{a.name}` given twice", a.span)
                self.expr(a.value)
            else:
                assigned[a.name] = a
        missing = [(n, t) for n, t in params if n not in assigned]
        if missing:
            lst = ", ".join(f"`{n}: {show(t)}`" for n, t in missing)
            self.error("E0206", f"missing argument(s) {lst} in call to `{display}`", span)
        for n, t in params:
            if n in assigned:
                self.expr(assigned[n].value, t)
        return ret

    def call_fn_type(self, ft, args, span):
        ft = prune(ft)
        if ft is ANY:
            for a in args:
                self.expr(a.value)
            return ANY
        if isinstance(ft, TVar):
            ps = [prune(self.expr(a.value)) for a in args]
            r = TVar()
            unify(ft, TFn(ps, r))
            return r
        if not isinstance(ft, TFn):
            self.error("E0210", f"`{show(ft)}` is not a function and cannot be called", span)
            for a in args:
                self.expr(a.value)
            return ANY
        for a in args:
            if a.name is not None:
                self.error("E0209", "named arguments cannot be used when calling a function value", a.span)
        if len(args) != len(ft.params):
            self.error("E0206", f"this function takes {len(ft.params)} argument(s) but {len(args)} were given", span)
        for a, pt in zip(args, ft.params):
            self.expr(a.value, pt)
        for a in args[len(ft.params):]:
            self.expr(a.value)
        return ft.ret

    def e_Call(self, e, exp):
        c = e.callee
        if isinstance(c, N.Name):
            v = self.lookup(c.name)
            if v is None:
                sig = self.fns.get(c.name) or self.globals.get(c.name)
                if sig is not None:
                    if c.name == "todo" and c.name not in self.fns:
                        what = e.args[0].value.parts[0] if (e.args and isinstance(e.args[0].value, N.StrLit)
                                                            and e.args[0].value.parts
                                                            and isinstance(e.args[0].value.parts[0], str)) else "..."
                        self.warn("W0404", f"unfinished code: todo(\"{what}\")", e.span,
                                  hint="replace `todo(...)` with a real implementation")
                    return self.call_sig(sig, e.args, e.span, expected=exp, node=e)
                if c.name in self.records:
                    self.error("E0210", f"`{c.name}` is a record type, not a function", c.span,
                               hint=self.record_hint(c.name))
                elif c.name in self.enums:
                    vs = ", ".join(f"`{c.name}.{x}`" for x in self.enums[c.name].variants)
                    self.error("E0210", f"`{c.name}` is an enum; construct one of its variants", c.span, hint=vs)
                elif c.name == "None":
                    self.error("E0210", "`None` takes no arguments", c.span, hint="write `None`")
                elif c.name in self.consts:
                    self.error("E0210", f"constant `{c.name}` is not a function", c.span)
                else:
                    special = {"len": "use the method: `xs.len()`", "str": "use `.to_str()`",
                               "int": "use `s.to_int()` (returns Option[Int])", "println": "use `print(...)`",
                               "console": "use `print(...)`", "printf": "use `print(\"... {x} ...\")`",
                               "assert_eq": "use `assert a == b`", "panic": "use `fail(\"message\")`",
                               "throw": "return `Err(...)` instead", "raise": "return `Err(...)` instead",
                               "open": "use `read_file(path)` / `write_file(path, text)` (effect `fs`)",
                               "input": "use `read_line()` (returns Option[Str], effect `io`)",
                               "sqrt": "use the method: `x.sqrt()`", "abs": "use the method: `x.abs()`",
                               "min": "use the method: `a.min(b)` or `xs.min()`",
                               "max": "use the method: `a.max(b)` or `xs.max()`",
                               "sum": "use the method: `xs.sum()`", "sorted": "use the method: `xs.sort()`",
                               "enumerate": "use the method: `xs.enumerate()`", "zip": "use the method: `xs.zip(ys)`"}
                    if c.name in special:
                        hint, fix = special[c.name], None
                    else:
                        hint, fix = self.did_you_mean(c.name, self.visible_names(), c.span)
                    self.error("E0201", f"unknown function `{c.name}`", c.span, hint=hint, fix=fix)
                for a in e.args:
                    self.expr(a.value)
                return ANY
            v.used = True
            return self.call_fn_type(v.type, e.args, e.span)
        ft = self.expr(c)
        return self.call_fn_type(ft, e.args, e.span)

    def variant_sig(self, enum, vname):
        info = self.enums[enum]
        t, mapping = self.fresh(info)
        params = [(f, subst(ft, mapping)) for f, ft in info.variants[vname]]
        return Sig(f"{enum}.{vname}", [], params, t, set())

    def is_type_name(self, obj):
        return isinstance(obj, N.Name) and self.lookup(obj.name) is None

    def e_MethodCall(self, e, exp):
        obj = e.obj
        if self.is_type_name(obj) and obj.name in self.enums:
            self.check_type_visible(obj.name, obj.span)
            variants = self.enums[obj.name].variants
            if e.method not in variants:
                h, fx = self.did_you_mean(e.method, variants, e.method_span)
                self.error("E0302", f"enum `{obj.name}` has no variant `{e.method}`", e.method_span,
                           hint=h or f"variants: {', '.join(variants)}", fix=fx)
                for a in e.args:
                    self.expr(a.value)
                return self.fresh(self.enums[obj.name])[0]
            if not variants[e.method]:
                self.error("E0206", f"variant `{obj.name}.{e.method}` has no fields; write it without parentheses",
                           e.span, fix={"span": e.span, "text": f"{obj.name}.{e.method}"})
                return self.fresh(self.enums[obj.name])[0]
            e.resolved = ("variant", obj.name, e.method)
            return self.call_sig(self.variant_sig(obj.name, e.method), e.args, e.span, expected=exp, node=e)
        if self.is_type_name(obj) and obj.name in ("Option", "Result"):
            self.error("E0204", f"`{obj.name}.{e.method}` does not exist", e.span,
                       hint="construct with `Some(x)` / `None` / `Ok(x)` / `Err(e)` directly")
            return ANY
        if self.is_type_name(obj) and obj.name in self.records:
            self.error("E0204", f"record types have no static methods (`{obj.name}.{e.method}`)", e.span,
                       hint=f"declare a function `fn {e.method}(...) -> {obj.name}` and call it directly")
            return ANY
        rt = prune(self.expr(obj))
        return self.method_call(rt, e, exp)

    def method_call(self, rt, e, exp):
        m = e.method
        if rt is ANY:
            for a in e.args:
                self.expr(a.value)
            return ANY
        if m == "to_str" and not e.args:
            e.resolved = ("to_str",)
            return STR
        h = head(rt)
        if h in self.records and m in self.records[h].fields:
            info = self.records[h]
            ft = subst(info.fields[m], self.args_map(info, rt))
            if isinstance(prune(ft), TFn):
                e.resolved = ("field_fn",)
                return self.call_fn_type(ft, e.args, e.span)
        if isinstance(rt, TVar):
            self.error("E0214", f"cannot infer the type of this value before calling `.{m}()`", e.obj.span,
                       hint="add a type annotation, e.g. `let xs: List[Int] = []`")
            for a in e.args:
                self.expr(a.value)
            return ANY
        bsig = BUILTIN_METHODS.get(h, {}).get(m) if h else None
        if bsig is not None:
            e.resolved = ("builtin", h, m)
            return self.call_sig(bsig, e.args, e.span, expected=exp, self_type=rt, display=m, node=e)
        usig = self.fns.get(m)
        if usig is not None and usig.params:
            first = subst(usig.params[0][1], {t: TVar() for t in usig.tparams})
            if unify(first, rt):
                e.resolved = ("ufcs", usig.module, usig.name)
                return self.call_sig(usig, e.args, e.span, expected=exp, self_type=rt, display=m, node=e)
        # error: unknown method
        cands = set(BUILTIN_METHODS.get(h, {})) | {"to_str"}
        for name, s in self.fns.items():
            if s and s.params and head(s.params[0][1]) == h:
                cands.add(name)
        hint, fix = None, None
        if m in FOREIGN_METHODS:
            target = FOREIGN_METHODS[m]
            if target and target in cands:
                hint, fix = f"Klar calls this method `{target}`", {"span": e.method_span, "text": target}
            elif m in FOREIGN_NOTES:
                hint = FOREIGN_NOTES[m]
        if hint is None:
            hint, fix = self.did_you_mean(m, cands, e.method_span)
        if hint is None and h in self.records and m in self.records[h].fields:
            hint = f"`{m}` is a field: write `.{m}` without parentheses"
        if hint is None:
            hint = f"methods of `{show(rt)}`: " + ", ".join(sorted(cands)) if cands else None
        self.error("E0204", f"type `{show(rt)}` has no method `{m}`", e.method_span, hint=hint, fix=fix)
        for a in e.args:
            self.expr(a.value)
        return ANY

    def e_FieldAccess(self, e, exp):
        obj = e.obj
        if self.is_type_name(obj) and obj.name in self.enums:
            self.check_type_visible(obj.name, obj.span)
            info = self.enums[obj.name]
            variants = info.variants
            if e.name not in variants:
                h, fx = self.did_you_mean(e.name, variants, e.name_span)
                self.error("E0302", f"enum `{obj.name}` has no variant `{e.name}`", e.name_span,
                           hint=h or f"variants: {', '.join(variants)}", fix=fx)
            elif variants[e.name]:
                fields = ", ".join(f"{f}: ..." for f, _ in variants[e.name])
                self.error("E0206", f"variant `{obj.name}.{e.name}` needs its fields", e.span,
                           hint=f"write `{obj.name}.{e.name}({fields})`")
            return self.fresh(info)[0]
        rt = prune(self.expr(obj))
        if rt is ANY:
            return ANY
        h = head(rt)
        if h in self.records:
            info = self.records[h]
            if e.name in info.fields:
                return subst(info.fields[e.name], self.args_map(info, rt))
            hint, fix = self.did_you_mean(e.name, info.fields, e.name_span)
            self.error("E0203", f"record `{h}` has no field `{e.name}`", e.name_span,
                       hint=hint or f"fields: {', '.join(info.fields)}", fix=fix)
            return ANY
        hint = None
        if h and (e.name in BUILTIN_METHODS.get(h, {}) or e.name == "to_str"):
            hint = f"`{e.name}` is a method: call it with `.{e.name}()`"
        elif h and e.name in FOREIGN_METHODS and FOREIGN_METHODS[e.name] in BUILTIN_METHODS.get(h, {}):
            hint = f"use the method `.{FOREIGN_METHODS[e.name]}()`"
        self.error("E0203", f"type `{show(rt)}` has no field `{e.name}`", e.name_span, hint=hint)
        return ANY

    def e_Try(self, e, exp):
        t = prune(self.expr(e.expr))
        ctx = self.ctx
        h = head(t)
        if h not in ("Option", "Result"):
            if isinstance(t, TVar):
                self.error("E0214", "cannot infer the type of the value before `?`", e.span,
                           hint="add a type annotation")
            elif t is not ANY:
                self.error("E0212", f"`?` can only be applied to `Option` or `Result`, found `{show(t)}`", e.span)
            return ANY
        inner = t.args[0]
        if ctx.is_test and ctx.purpose == "test":
            return inner
        if ctx.purpose in ("contract", "const"):
            self.error("E0212", f"`?` is not allowed in {'contracts' if ctx.purpose == 'contract' else 'constants'}",
                       e.span)
            return inner
        r = prune(ctx.ret)
        if isinstance(r, TVar):
            unify(r, option_of(TVar()) if h == "Option" else result_of(TVar(), t.args[1]))
            return inner
        if h == "Option":
            if head(r) != "Option":
                self.error("E0212", f"`?` on an `Option` needs the enclosing function to return `Option[...]`, "
                                    f"but `{ctx.name}` returns `{show(r)}`", e.span,
                           hint="use `match`, `.unwrap_or(default)`, or convert with `.ok_or(error)?`")
            return inner
        if head(r) != "Result":
            self.error("E0212", f"`?` on a `Result` needs the enclosing function to return `Result[...]`, "
                                f"but `{ctx.name}` returns `{show(r)}`", e.span,
                       hint=f"change the return type to `Result[{show(r)}, {show(t.args[1])}]` or handle the error with `match`")
            return inner
        if not unify(r.args[1], t.args[1]):
            self.error("E0212", f"`?` would propagate error type `{show(t.args[1])}`, but `{ctx.name}` returns "
                                f"errors of type `{show(r.args[1])}`", e.span,
                       hint="convert the error first: `.map_err(fn(e) => ...)?`")
        return inner

    def e_RecordLit(self, e, exp):
        name = e.type_name
        if name not in self.records:
            if name in self.enums:
                self.error("E0104", f"`{name}` is an enum, not a record", e.span,
                           hint=f"construct a variant: `{name}.Variant(...)`")
            elif name in self.aliases:
                self.error("E0104", f"`{name}` is a type alias; construct the underlying type instead", e.span)
            else:
                hint, fix = self.did_you_mean(name, [r for r in self.records if r in self.visible], e.span)
                self.error("E0104", f"unknown record type `{name}`", e.span, hint=hint)
            for f in e.fields:
                self.expr(f.value)
            return ANY
        self.check_type_visible(name, e.span)
        info = self.records[name]
        t, mapping = self.fresh(info)
        if exp is not None:
            unify(t, exp)
        fields = info.fields
        seen = set()
        for f in e.fields:
            if f.name not in fields:
                hint, fix = self.did_you_mean(f.name, fields, f.span)
                self.error("E0203", f"record `{name}` has no field `{f.name}`", f.span,
                           hint=hint or f"fields: {', '.join(fields)}")
                self.expr(f.value)
            elif f.name in seen:
                self.error("E0209", f"field `{f.name}` given twice", f.span)
            else:
                seen.add(f.name)
                self.expr(f.value, subst(fields[f.name], mapping))
        missing = [f for f in fields if f not in seen]
        if missing:
            self.error("E0209", f"missing field(s) {', '.join('`' + m + '`' for m in missing)} in `{name}`", e.span,
                       hint="every field must be given (Klar has no default values); "
                            "to copy with changes use `old with { field: value }`")
        return t

    def e_WithExpr(self, e, exp):
        bt = prune(self.expr(e.base))
        h = head(bt)
        if bt is ANY:
            for f in e.fields:
                self.expr(f.value)
            return ANY
        if h not in self.records:
            self.error("E0202", f"`with` needs a record value, found `{show(bt)}`", e.base.span)
            return ANY
        info = self.records[h]
        mapping = self.args_map(info, bt)
        for f in e.fields:
            if f.name not in info.fields:
                hint, fix = self.did_you_mean(f.name, info.fields, f.span)
                self.error("E0203", f"record `{h}` has no field `{f.name}`", f.span, hint=hint)
                self.expr(f.value)
            else:
                self.expr(f.value, subst(info.fields[f.name], mapping))
        return bt

    def e_Lambda(self, e, exp):
        ex = prune(exp) if exp is not None else None
        efn = ex if isinstance(ex, TFn) else None
        if efn is not None and len(efn.params) != len(e.params):
            self.error("E0206", f"this function must take {len(efn.params)} parameter(s), "
                                f"but the lambda declares {len(e.params)}", e.span)
            efn = None
        ptypes = []
        for i, p in enumerate(e.params):
            if p.type is not None:
                t = self.resolve(p.type, self.tparams)
            elif efn is not None:
                t = efn.params[i]
            else:
                t = TVar()
            ptypes.append(t)
        if e.ret is not None:
            ret = self.resolve(e.ret, self.tparams)
        elif efn is not None:
            ret = efn.ret
        else:
            ret = TVar()
        outer = self.ctx
        purpose = outer.purpose if outer.purpose in ("test", "contract", "const") else "lambda"
        e.ptypes, e.ret_t = ptypes, ret
        self.ctx = Ctx(outer.name, ret, outer.effects, purpose=purpose, sig_end=outer.sig_end)
        self.ctx.is_test = False
        self.push()
        for p, t in zip(e.params, ptypes):
            self.declare(p.name, t, False, p.span, "param")
        if isinstance(e.body, N.Block):
            self.block(e.body)
            r = prune(ret)
            if not self.returns(e.body):
                if isinstance(r, TVar):
                    unify(r, UNIT)
                elif not is_unit(r) and r is not ANY and r is not NEVER:
                    self.error("E0205", f"lambda may reach its end without returning `{show(r)}`", e.span,
                               hint="add `return <value>`, or use the short form `fn(x) => expr`")
        else:
            self.expr(e.body, ret)
        self.pop()
        self.ctx = outer
        return TFn(ptypes, ret)

    # ---- match -----------------------------------------------------------------
    def e_Match(self, e, exp):
        st = prune(self.expr(e.subject))
        result = TVar()
        if exp is not None:
            unify(result, exp)
        catch_all = False
        covered = set()
        for arm in e.arms:
            if catch_all:
                self.warn("W0303", "unreachable match arm (an earlier arm matches everything)", arm.pattern.span)
            self.push()
            self.pattern(arm.pattern, st)
            if arm.guard is not None:
                self.expr(arm.guard, BOOL)
            if isinstance(arm.body, N.Block):
                self.block(arm.body)
                if not self.returns(arm.body):
                    if not unify(result, UNIT):
                        self.error("E0202", f"this block arm has type `Unit`, but other arms produce "
                                            f"`{show(result)}`", arm.body.span,
                                   hint="use an expression arm (`pattern => value`) or `return` inside the block")
            else:
                at = self.expr(arm.body)
                if not unify(result, at):
                    self.error("E0202", f"match arms have different types: `{show(result)}` and `{show(at)}`",
                               arm.body.span)
            self.pop()
            if arm.guard is not None:
                continue  # guarded arms never count for exhaustiveness
            p = arm.pattern
            if isinstance(p, (N.PWild, N.PBind)):
                catch_all = True
            elif isinstance(p, N.PVariant) and all(self.irrefutable(a) for a in p.args):
                covered.add(p.variant)
            elif isinstance(p, N.PLit) and isinstance(p.value, bool):
                covered.add(p.value)
        if not catch_all:
            self.exhaustive(st, covered, e)
        return result

    def irrefutable(self, p):
        return isinstance(p, (N.PWild, N.PBind))

    def exhaustive(self, st, covered, e):
        h = head(st)
        needed, render = None, None
        if h == "Bool":
            needed = [True, False]
            render = lambda v: "true" if v else "false"
        elif h == "Option":
            needed = ["Some", "None"]
            render = lambda v: "Some(value)" if v == "Some" else "None"
        elif h == "Result":
            needed = ["Ok", "Err"]
            render = lambda v: "Ok(value)" if v == "Ok" else "Err(error)"
        elif h in self.enums:
            fields = self.enums[h].variants
            needed = list(fields)
            render = lambda v: f"{h}.{v}" + (f"({', '.join(f for f, _ in fields[v])})" if fields[v] else "")
        if needed is None:
            if st is ANY or isinstance(st, TVar):
                return
            self.error("E0301", f"match on `{show(st)}` needs a catch-all arm", e.span,
                       hint="add `_ => ...` as the last arm")
            return
        missing = [v for v in needed if v not in covered]
        if missing:
            arms = ", ".join(f"`{render(v)} => ...`" for v in missing)
            self.error("E0301", f"non-exhaustive match on `{show(st)}`: missing {arms}", e.span,
                       hint="add the missing arms, or a catch-all `_ => ...` (arms with `if` guards do not count)")

    def pattern(self, p, t):
        t = prune(t)
        p.kt = t
        if isinstance(p, N.PWild):
            return
        if isinstance(p, N.PBind):
            self.declare(p.name, t, False, p.span, "bind")
            return
        if isinstance(p, N.PLit):
            lt = BOOL if isinstance(p.value, bool) else INT if isinstance(p.value, int) else \
                FLOAT if isinstance(p.value, float) else STR
            if not unify(lt, t):
                self.error("E0302", f"pattern of type `{show(lt)}` cannot match a value of type `{show(t)}`", p.span)
            return
        if isinstance(p, N.PVariant):
            if p.enum is None:
                if p.variant in ("Some", "None"):
                    inner = TVar()
                    if not unify(option_of(inner), t):
                        self.error("E0302", f"`{p.variant}` matches `Option`, but the value has type `{show(t)}`", p.span)
                        inner = ANY
                    for a in p.args:
                        self.pattern(a, inner)
                    return
                ok_t, err_t = TVar(), TVar()
                if not unify(result_of(ok_t, err_t), t):
                    self.error("E0302", f"`{p.variant}` matches `Result`, but the value has type `{show(t)}`", p.span)
                    ok_t = err_t = ANY
                for a in p.args:
                    self.pattern(a, ok_t if p.variant == "Ok" else err_t)
                return
            if p.enum not in self.enums:
                hint, fix = self.did_you_mean(p.enum, self.enums, p.span)
                self.error("E0302", f"unknown enum `{p.enum}` in pattern", p.span, hint=hint)
                for a in p.args:
                    self.pattern(a, ANY)
                return
            self.check_type_visible(p.enum, p.span)
            info = self.enums[p.enum]
            inst, _ = self.fresh(info)
            if not unify(inst, t):
                self.error("E0302", f"pattern `{p.enum}.{p.variant}` has type `{p.enum}`, "
                                    f"but the value has type `{show(t)}`", p.span)
            mapping = self.args_map(info, inst)
            variants = info.variants
            if p.variant not in variants:
                hint, fix = self.did_you_mean(p.variant, variants, p.span)
                self.error("E0302", f"enum `{p.enum}` has no variant `{p.variant}`", p.span,
                           hint=hint or f"variants: {', '.join(variants)}")
                for a in p.args:
                    self.pattern(a, ANY)
                return
            fields = variants[p.variant]
            if len(p.args) != len(fields):
                names = ", ".join(f for f, _ in fields)
                self.error("E0302", f"`{p.enum}.{p.variant}` has {len(fields)} field(s)"
                                    f"{' (' + names + ')' if names else ''}, but the pattern has {len(p.args)}",
                           p.span, hint=f"write `{p.enum}.{p.variant}({names})`" if names else
                           f"write `{p.enum}.{p.variant}` without parentheses")
            for a, (_, ft) in zip(p.args, fields):
                self.pattern(a, subst(ft, mapping))
            for a in p.args[len(fields):]:
                self.pattern(a, ANY)

    # ---- module interface ------------------------------------------------------
    def exports(self):
        """Everything a module declares can be imported (visibility control is planned)."""
        out = {}
        for d in self.program.decls:
            if isinstance(d, N.FnDecl) and isinstance(self.fns.get(d.name), Sig) and self.fns[d.name].decl is d:
                out[d.name] = ("fn", self.fns[d.name])
            elif isinstance(d, N.ConstDecl) and d.name in self.consts:
                out[d.name] = ("const", self.consts[d.name])
            elif isinstance(d, (N.TypeDecl, N.EnumDecl, N.AliasDecl)) and self.universe.owner(d.name) == self.module:
                out[d.name] = ("type", d.name)
        return out


def is_lit(e):
    """Integer literal arithmetic (typed as Word or Int by context in system modules)."""
    if isinstance(e, N.IntLit):
        return True
    if isinstance(e, N.Binary) and e.op in ("+", "-", "*", "/", "%"):
        return is_lit(e.left) and is_lit(e.right)
    if isinstance(e, N.Unary) and e.op == "-":
        return is_lit(e.operand)
    return False


def to_snake(name):
    s = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
    return s.replace("__", "_")
