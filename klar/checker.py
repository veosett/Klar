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
from .types import (ANY, BOOL, FLOAT, INT, NEVER, STR, UNIT, Eff, TCon, TFn, TParam, TVar, eff_names, eprune, flex,
                    head, is_unit, list_of, map_of, option_of, prune, result_of, show, subst, unify)

KNOWN_EFFECTS = {"io", "time", "rand", "fs", "net", "proc"}
PRIMS = {"Int", "Float", "Bool", "Str", "Bytes", "Unit", "Never"}
GENERIC_ARITY = {"List": 1, "Map": 2, "Option": 1, "Result": 2}
PASCAL = re.compile(r"^[A-Z][A-Za-z0-9]*$")
SNAKE = re.compile(r"^_?[a-z][a-z0-9_]*$|^_$")
UPPER = re.compile(r"^[A-Z][A-Z0-9_]*$")


class Sig:
    def __init__(self, name, tparams, params, ret, effects, decl=None, user=False, module=None, bounds=None):
        self.name = name
        self.bounds = bounds or {}  # type parameter -> [trait names]
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
        self.newtype = False      # `type X = new T`: built only by its constructor `X(value)`
        self.invariant = False    # a newtype with `requires` lines


class EnumInfo:
    def __init__(self, name, tparams, module, span):
        self.name, self.tparams, self.module, self.span = name, tparams, module, span
        self.variants = {}


class AliasInfo:
    def __init__(self, name, tparams, target, module, span):
        self.name, self.tparams, self.target, self.module, self.span = name, tparams, target, module, span
        self.resolving = False


class TraitInfo:
    def __init__(self, name, module, span):
        self.name, self.module, self.span = name, module, span
        self.methods = {}     # method -> Sig generic in `Self` (first parameter `self: Self`)
        self.defaults = {}    # method -> Sig of the default body (`Trait.m`)


class ImplInfo:
    def __init__(self, trait, type_name, module, span, target=None, tparams=(), bounds=None):
        self.trait, self.type_name, self.module, self.span = trait, type_name, module, span
        self.methods = {}     # method -> Sig of `Type.m`
        # a generic impl (`impl[T: Show] Show for List[T]`): the target `List[T]`, its parameters and their bounds
        self.target = target if target is not None else TCon(type_name)
        self.tparams = list(tparams)
        self.bounds = bounds or {}


class Universe:
    """Program-wide registry of type and trait declarations (names are unique per program)."""

    def __init__(self):
        self.records = {}
        self.enums = {}
        self.aliases = {}
        self.traits = {}
        self.impls = {}          # (trait, type name) -> ImplInfo
        self.type_methods = {}   # type name -> {method: (trait, Sig)} (impl methods and inherited defaults)

    def implements(self, type_name, trait):
        return (trait, type_name) in self.impls

    def missing_impl(self, t, trait, ctx_bounds):
        """None when type `t` implements `trait` (with the bounds of a generic impl satisfied, recursively), else
        (type, trait) of the first requirement that fails. `ctx_bounds`: the bounds of the type parameters in scope."""
        t = prune(t)
        if t is ANY or t is NEVER or isinstance(t, TVar):
            return None
        if isinstance(t, TParam):
            return None if trait in ctx_bounds.get(t.name, ()) else (t, trait)
        info = self.impls.get((trait, head(t))) if isinstance(t, TCon) else None
        if info is None or len(t.args) != len(info.tparams):
            return (t, trait)
        for arg, tp in zip(t.args, info.target.args):
            for tr in info.bounds.get(tp.name, ()):
                miss = self.missing_impl(arg, tr, ctx_bounds)
                if miss is not None:
                    return miss
        return None

    def owner(self, name):
        for table in (self.records, self.enums, self.aliases, self.traits):
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
        self.purpose = purpose  # fn | lambda | test | contract | const | parallel (the function of a par_map)
        self.used = set()        # the effects the body uses (a lambda's type gets them)
        self.fn_type = None      # purpose "fntype": the written function type a lambda must fit


def freeze(t, seen=None):
    """The effects of the function types in a `var` are fixed at its declaration: a later assignment cannot
    widen them for uses already checked."""
    t = prune(t)
    if isinstance(t, TFn):
        e = eprune(t.eff)
        if not e.fixed:
            e.ref = Eff(e.names)
        for p in t.params:
            freeze(p)
        freeze(t.ret)
    elif isinstance(t, TCon):
        for a in t.args:
            freeze(a)


def _resolve_builtin_type(te, tps):
    if isinstance(te, N.FnTypeExpr):
        # a function parameter of a built-in is polymorphic in its effects: `xs.map(f)` does what `f` does
        return TFn([_resolve_builtin_type(p, tps) for p in te.params], _resolve_builtin_type(te.ret, tps),
                   Eff(te.effects) if te.effects else Eff(poly=True))
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
        self.bounds = {}       # type parameter -> set of traits (current function)
        self.pending = []      # calls of bounded generic functions, checked when the body is done
        self.methods = {}      # "Type.m" / "Trait.m" -> Sig (trait/impl methods; not callable by name)
        self.traits = self.universe.traits
        self.const_allowed = None
        for name, (kind, value) in (imports or {}).items():
            self.imported.add(name)
            if kind == "fn":
                self.fns[name] = value
                if value.decl is not None and value.decl.constructs:
                    self.visible.add(name)          # a newtype: its constructor and its type
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
                self.bounds = {}
                self.check_const(d)
                self.check_pending()
        for d in self.program.decls:
            if isinstance(d, N.FnDecl):
                self.check_fn(d)
                self.check_pending()
            elif isinstance(d, N.TestDecl):
                self.check_test(d)
                self.check_pending()
            elif isinstance(d, N.PropertyDecl):
                self.check_property(d)
                self.check_pending()
        if "main" in self.fns and "main" not in self.imported:
            sig = self.fns["main"]
            ret = prune(sig.ret)
            ok_ret = is_unit(ret) or (head(ret) == "Result" and is_unit(ret.args[0]))
            if sig.params or not ok_ret:
                self.error("E0502", "`main` must take no parameters and return `Unit` or `Result[Unit, E]`",
                           sig.decl.name_span)
        self.unused_private_functions()
        self.diags.sort(key=lambda d: (d.span.file != self.file, d.span.line, d.span.col))
        return self.diags

    def unused_private_functions(self):
        if self.all_public():
            return
        own = {d.name: d for d in self.program.decls
               if isinstance(d, N.FnDecl) and not d.owner_kind and not d.constructs and not d.public and d.name != "main"
               and isinstance(self.fns.get(d.name), Sig) and self.fns[d.name].decl is d}
        if not own:
            return
        used = set()
        for d in self.program.decls:
            for n in N.walk(d):
                if isinstance(n, N.Name) and n.name in own and own[n.name] is not d:
                    used.add(n.name)
                elif isinstance(n, N.MethodCall):
                    res = getattr(n, "resolved", None)
                    if res and res[0] == "ufcs" and res[2] in own and own[res[2]] is not d:
                        used.add(res[2])
        for name, d in own.items():
            if name not in used:
                self.warn("W0406", f"function `{name}` is never used", d.name_span,
                          hint="remove it, call it, or mark it `pub` if other modules should use it",
                          fix={"span": Span(d.span.file, d.span.line, d.span.col, d.span.line, d.span.col),
                               "text": "pub ", "safe": False})

    # ---- declarations --------------------------------------------------------
    def type_names_visible(self):
        return self.visible | PRIMS | set(GENERIC_ARITY)

    def collect(self):
        test_names = set()
        own_types = []
        own_traits = []
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
            elif isinstance(d, N.TraitDecl):
                if not PASCAL.match(d.name):
                    self.error("E0103", f"trait name `{d.name}` must be PascalCase", d.name_span)
                owner = self.universe.owner(d.name)
                if owner is not None or d.name in PRIMS or d.name in GENERIC_ARITY:
                    self.error("E0101", f"`{d.name}` is already defined" + (f" in module `{owner}`" if owner and
                               owner != self.module else ""), d.name_span,
                               hint="trait and type names are unique across the whole program")
                    continue
                self.traits[d.name] = TraitInfo(d.name, self.module, d.name_span)
                self.visible.add(d.name)
                own_traits.append(d)
            elif isinstance(d, N.FnDecl) and d.owner_kind:
                continue
            elif isinstance(d, N.FnDecl):
                if d.name in self.fns or d.name in self.globals or d.name in self.consts:
                    what = ("a built-in function" if d.name in self.globals else
                            "imported" if d.name in self.imported else "already defined")
                    self.error("E0101", f"function `{d.name}` is {what}", d.name_span)
                    continue
                if d.constructs:
                    if d.constructs in self.records and self.records[d.constructs].module == self.module:
                        self.records[d.constructs].newtype = True
                        self.records[d.constructs].invariant = bool(d.requires)
                elif not SNAKE.match(d.name):
                    self.warn("W0104", f"function name `{d.name}` should be snake_case", d.name_span,
                              hint=snake_hint(d.name))
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
            if isinstance(d, N.FnDecl) and not d.owner_kind and self.fns.get(d.name, 0) is None:
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
                                   hint=h or "known effects: io, time, rand, fs, net, proc")
                self.fns[d.name] = Sig(d.name, d.type_params, params, ret, d.effects, decl=d, user=True,
                                       module=self.module, bounds=self.resolve_bounds(d))
        self.collect_traits(own_traits)

    # ---- traits & impls --------------------------------------------------------------
    def resolve_bounds(self, d):
        out = {}
        for tp, items in (d.bounds or {}).items():
            if tp not in d.type_params:
                continue
            names = []
            for tname, sp in items:
                if tname not in self.traits:
                    hint, fix = self.did_you_mean(tname, [t for t in self.traits if t in self.visible], sp)
                    if tname in self.records or tname in self.enums or tname in PRIMS:
                        hint = f"`{tname}` is a type; a bound names a trait (`trait Name {{ ... }}`)"
                    self.error("E0104", f"unknown trait `{tname}`", sp, hint=hint, fix=fix)
                    continue
                if tname not in self.visible:
                    self.not_imported(tname, sp)
                if tname not in names:
                    names.append(tname)
            out[tp] = names
        return out

    def method_sig(self, d, self_type, impl_bounds=None):
        """Signature of a trait/impl method; `Self` is `self_type` (impl_bounds: those of a generic impl)."""
        tps = {t: TParam(t) for t in d.type_params}
        tps["Self"] = self_type
        params = [(p.name, self.resolve(p.type, tps)) for p in d.params]
        ret = self.resolve(d.ret, tps) if d.ret else UNIT
        for e in d.effects:
            if e not in KNOWN_EFFECTS:
                self.error("E0403", f"unknown effect `{e}`", d.effects_span, hint="known effects: io, time, rand, fs, net, proc")
        return Sig(d.name, list(d.type_params), params, ret, d.effects, decl=d, user=True, module=self.module,
                   bounds={"Self": [d.trait]} if d.owner_kind == "default" else dict(impl_bounds or {}))

    def collect_traits(self, own_traits):
        for d in own_traits:
            info = self.traits[d.name]
            for f in d.methods:
                if f.method in info.methods:
                    self.error("E0101", f"duplicate method `{f.method}` in trait `{d.name}`", f.name_span)
                    continue
                info.methods[f.method] = self.method_sig(f, TParam("Self"))
                info.methods[f.method].name = f.method
                info.methods[f.method].tparams = ["Self"]
        for d in self.program.decls:
            if isinstance(d, N.FnDecl) and d.owner_kind == "default" and d.trait in self.traits:
                info = self.traits[d.trait]
                if d.method in info.methods:
                    self.error("E0101", f"duplicate method `{d.method}` in trait `{d.trait}`", d.name_span)
                    continue
                sig = self.method_sig(d, TParam("Self"))
                self.methods[d.name] = sig
                info.defaults[d.method] = sig
                generic = Sig(d.method, sig.tparams, sig.params, sig.ret, sig.effects, decl=None, user=True,
                              module=self.module)
                info.methods[d.method] = generic
        impl = None
        for d in self.program.decls:
            if isinstance(d, N.ImplDecl):
                impl = self.collect_impl(d)
            elif isinstance(d, N.FnDecl) and d.owner_kind == "impl" and impl is not None:
                decl, target, info, tinfo = impl
                sig = self.method_sig(d, target, decl.resolved_bounds)
                if d.name in self.methods:
                    self.error("E0101", f"`{d.owner}` already has a method `{d.method}`", d.name_span)
                    continue
                self.methods[d.name] = sig
                sig.self_type = target
                if info is not None:
                    info.methods[d.method] = sig
        for d in self.program.decls:
            if isinstance(d, N.ImplDecl) and getattr(d, "info", None) is not None:
                self.finish_impl(d)

    def collect_impl(self, d):
        """Returns (decl, target type, ImplInfo or None, TraitInfo or None)."""
        tps = {t: TParam(t) for t in d.type_params}
        for t in d.type_params:
            if not PASCAL.match(t):
                self.error("E0103", f"type parameter `{t}` must be PascalCase (e.g. `T`)", d.span)
        target = self.resolve(d.target, tps)
        d.resolved_bounds = self.resolve_bounds(d)
        d.info = None
        tname = head(target)
        trait = self.traits.get(d.trait)
        if trait is None:
            hint, fix = self.did_you_mean(d.trait, [t for t in self.traits if t in self.visible], d.trait_span)
            if d.trait in self.records or d.trait in self.enums:
                hint = f"`{d.trait}` is a type; `impl` needs a trait: `impl Trait for {d.trait}`"
            self.error("E0104", f"unknown trait `{d.trait}`", d.trait_span, hint=hint, fix=fix)
            return d, target, None, None
        if d.trait not in self.visible:
            self.not_imported(d.trait, d.trait_span)
        if target is ANY:
            return d, target, None, trait
        if not isinstance(target, TCon) or tname in ("Unit", "Never", "Word"):
            self.error("E0221", f"cannot implement `{d.trait}` for `{show(target)}`", d.target.span,
                       hint="impls are written for Int, Float, Bool, Str, Bytes, `type`/`enum` declarations and "
                            "List, Map, Option, Result")
            return d, target, None, trait
        params = self.type_param_names(tname)
        if params:
            names = [a.name for a in target.args if isinstance(a, TParam)]
            if len(names) != len(target.args) or len(set(names)) != len(names) or \
                    sorted(names) != sorted(d.type_params):
                ps = ", ".join(d.type_params if len(d.type_params) == len(params) else params)
                self.error("E0221", f"cannot implement `{d.trait}` for `{show(target)}`", d.target.span,
                           hint=f"an impl covers every `{tname}`: write `impl[{ps}] {d.trait} for {tname}[{ps}]`")
                return d, target, None, trait
        elif d.type_params:
            self.error("E0221", f"`{tname}` has no type parameters for the impl's `{d.type_params[0]}`", d.target.span,
                       hint=f"write `impl {d.trait} for {tname}`")
            return d, target, None, trait
        type_owner = self.universe.owner(tname)
        if trait.module != self.module and type_owner != self.module:
            where = f"module `{trait.module}`" + (f" or `{type_owner}`" if type_owner else "")
            self.error("E0222", f"`impl {d.trait} for {tname}` must be written in {where}", d.span,
                       hint="an impl lives next to its trait or next to its type, so every program sees the same one")
        if (d.trait, tname) in self.universe.impls:
            prev = self.universe.impls[(d.trait, tname)]
            self.error("E0222", f"`{tname}` already implements `{d.trait}` (at {prev.span.short()})", d.span)
            return d, target, None, trait
        info = ImplInfo(d.trait, tname, self.module, d.span, target, d.type_params, d.resolved_bounds)
        d.info = info
        self.universe.impls[(d.trait, tname)] = info
        return d, target, info, trait

    def finish_impl(self, d):
        info = d.info
        trait = self.traits[info.trait]
        tname = info.type_name
        target = info.target
        for m, sig in info.methods.items():
            span = d.method_spans[d.methods.index(m)] if m in d.methods else d.span
            if m not in trait.methods:
                hint, fix = self.did_you_mean(m, trait.methods, span)
                self.error("E0221", f"`{m}` is not a method of trait `{info.trait}`", span,
                           hint=hint or (f"methods of `{info.trait}`: {', '.join(trait.methods)}; "
                                         "other functions go outside the impl"), fix=fix)
                continue
            if m == "to_str" or m in BUILTIN_METHODS.get(tname, {}):
                self.error("E0221", f"`{tname}` already has a built-in method `{m}`", span,
                           hint="rename the trait method")
                continue
            if m in self.fns and self.fns[m] and self.fns[m].params and head(self.fns[m].params[0][1]) == tname:
                self.error("E0101", f"method `{m}` of `{tname}` conflicts with the function `{m}`", span,
                           hint="rename one of them")
                continue
            want = trait.methods[m]
            problem = self.signature_mismatch(want, sig, target)
            if problem:
                self.error("E0221", f"`{tname}.{m}` does not match the trait: {problem}", span,
                           hint=f"the trait declares `{self.show_method(want, target)}`")
        missing = [m for m in trait.methods if m not in info.methods and m not in trait.defaults]
        if missing:
            stubs = "".join(f"  {self.show_method(trait.methods[m], target)} {{\n    return todo(\"{m}\")\n  }}\n"
                            for m in missing)
            end = d.span
            fix = {"span": Span(end.file, end.end_line, end.end_col - 1, end.end_line, end.end_col - 1),
                   "text": stubs, "safe": True}
            self.error("E0221", f"`impl {info.trait} for {tname}` is missing "
                                f"{', '.join(f'`{m}`' for m in missing)}", d.span,
                       hint="add " + ", ".join(f"`{self.show_method(trait.methods[m], target)}`" for m in missing),
                       fix=fix)
        table = self.universe.type_methods.setdefault(tname, {})
        for m in trait.methods:
            sig = info.methods.get(m) or trait.defaults.get(m) or trait.methods[m]  # (missing: already an error)
            if m in table and table[m][0] != info.trait:
                self.error("E0101", f"`{tname}` gets method `{m}` from both `{table[m][0]}` and `{info.trait}`",
                           d.span, hint="rename the method in one of the traits")
                continue
            table[m] = (info.trait, sig)

    def show_method(self, sig, self_type):
        m = {"Self": self_type}
        ps = ["self"] + [f"{n}: {show(subst(t, m))}" for n, t in sig.params[1:]]
        ret = subst(sig.ret, m)
        out = f"fn {sig.name.split('.')[-1]}({', '.join(ps)})"
        if not is_unit(ret):
            out += f" -> {show(ret)}"
        if sig.effects:
            out += " uses " + ", ".join(sorted(sig.effects))
        return out

    def signature_mismatch(self, want, got, target):
        m = {"Self": target}
        if len(want.params) != len(got.params):
            return f"it takes {len(got.params) - 1} argument(s) besides `self`, the trait says {len(want.params) - 1}"
        for (wn, wt), (gn, gt) in zip(want.params[1:], got.params[1:]):
            if wn != gn:
                return f"parameter `{gn}` should be named `{wn}`"
            if show(subst(wt, m)) != show(gt):
                return f"parameter `{gn}` has type `{show(gt)}`, the trait says `{show(subst(wt, m))}`"
        if show(subst(want.ret, m)) != show(got.ret):
            return f"it returns `{show(got.ret)}`, the trait says `{show(subst(want.ret, m))}`"
        extra = got.effects - want.effects
        if extra:
            return f"it uses `{', '.join(sorted(extra))}`, which the trait method does not declare"
        return None

    def note_bounds(self, sig, mapping, span):
        if sig.bounds:
            self.pending.append((sig, mapping, span, {k: set(v) for k, v in self.bounds.items()}))

    def check_pending(self):
        pending, self.pending = self.pending, []
        for sig, mapping, span, ctx_bounds in pending:
            for tp, traits in sig.bounds.items():
                t = prune(mapping.get(tp, ANY))
                name = sig.name if "." not in sig.name else sig.name.split(".")[-1]
                for tr in traits:
                    if t is ANY or t is NEVER:
                        continue
                    if isinstance(t, TVar):
                        self.error("E0223", f"cannot infer `{tp}` for `{name}` (it must implement `{tr}`)", span,
                                   hint="annotate the value, e.g. `let xs: List[Circle] = []`")
                        break
                    if isinstance(t, TParam):
                        if tr not in ctx_bounds.get(t.name, ()):
                            self.error("E0220", f"type parameter `{t.name}` must implement `{tr}` to call `{name}`",
                                       span, hint=f"add the bound to the type parameter: `[{t.name}: {tr}]`")
                        continue
                    miss = self.universe.missing_impl(t, tr, ctx_bounds)
                    if miss is None:
                        continue
                    if miss != (t, tr):
                        self.error("E0220", f"`{show(t)}` does not implement trait `{tr}` (needed by `{name}`)", span,
                                   hint=f"`{show(t)}` implements `{tr}` only if `{show(miss[0])}` implements "
                                        f"`{miss[1]}`")
                        continue
                    h = head(t)
                    params = self.type_param_names(h)
                    for_t = show(t) if not params else f"{h}[{', '.join(params)}]"
                    gen = f"[{', '.join(params)}]" if params else ""
                    methods = ", ".join(f"`{self.show_method(s, t)}`" for s in self.traits[tr].methods.values()
                                        if s.name.split(".")[-1] not in self.traits[tr].defaults)
                    self.error("E0220", f"`{show(t)}` does not implement trait `{tr}` (needed by `{name}`)", span,
                               hint=f"add `impl{gen} {tr} for {for_t} {{ ... }}`" + (f" with {methods}" if methods else ""))

    def type_param_names(self, tname):
        """The type parameters of a generic type (`List` → [T]); [] for other types."""
        if tname in GENERIC_ARITY:
            return {"List": ["T"], "Map": ["K", "V"], "Option": ["T"], "Result": ["T", "E"]}[tname]
        if tname in self.records:
            return list(self.records[tname].tparams)
        if tname in self.enums:
            return list(self.enums[tname].tparams)
        return []

    def not_imported(self, name, span):
        owner = self.universe.owner(name)
        self.error("E0104", f"type `{name}` is defined in module `{owner}` but not imported here", span,
                   hint=f"add `use {owner}.{{{name}}}` at the top of the file")

    def resolve(self, te, tps):
        if te is None:
            return ANY
        if isinstance(te, N.FnTypeExpr):
            for e in te.effects:
                if e not in KNOWN_EFFECTS:
                    h, _ = self.did_you_mean(e, KNOWN_EFFECTS, te.span)
                    self.error("E0403", f"unknown effect `{e}`", te.span,
                               hint=h or "known effects: io, time, rand, fs, net, proc")
            return TFn([self.resolve(p, tps) for p in te.params], self.resolve(te.ret, tps),
                       Eff(e for e in te.effects if e in KNOWN_EFFECTS))
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
        if name in self.traits:
            self.error("E0224", f"`{name}` is a trait, not a type", te.span,
                       hint=f"use a type parameter with a bound: `fn f[T: {name}](x: T)`; "
                            f"for a list of different kinds of values use an `enum` (and `impl {name}` for it)")
            return ANY
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
                   "Maybe": "Option", "Either": "Result", "Tuple": "Pair", "bytes": "Bytes", "bytearray": "Bytes",
                   "Buffer": "Bytes", "ByteArray": "Bytes", "u8": "Int", "byte": "Int"}
        cands = self.type_names_visible() | set(tps)
        if name == "Self":
            self.error("E0104", "`Self` is only available in `trait` and `impl` methods", te.span,
                       hint="write the concrete type name")
            return ANY
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
            if not v.used and not name.startswith("_") and name != "self" and v.kind in ("let", "var", "param", "for", "bind"):
                what = {"param": "parameter", "for": "loop variable", "bind": "pattern variable"}.get(v.kind, "variable")
                self.warn("W0402", f"unused {what} `{name}`", v.span,
                          hint=f"remove it or rename it to `_{name}`")

    def lookup(self, name):
        for sc in reversed(self.scopes):
            if name in sc:
                return sc[name]
        return None

    def captured_var(self, name, span, assigning=False):
        """A lambda may only capture immutable bindings: a captured `var` would be ambiguous
        (snapshot or shared?) and is a classic source of closure bugs."""
        bounds = getattr(self, "lambda_bounds", None)
        if not bounds:
            return
        for i in range(len(self.scopes) - 1, -1, -1):
            if name in self.scopes[i]:
                v = self.scopes[i][name]
                depth, serial = bounds[-1]
                if v.mutable and i < depth:
                    key = (name, serial)   # once per variable and lambda
                    reported = self.__dict__.setdefault("reported_captures", set())
                    if key in reported:
                        return
                    reported.add(key)
                    if assigning:
                        self.error("E0216", f"a lambda cannot assign `{name}`, a `var` of the enclosing function",
                                   span, hint="lambdas cannot change outer variables: accumulate with "
                                              "`xs.fold(start, fn(acc, x) => ...)` or use a `for` loop")
                    else:
                        self.error("E0216", f"a lambda cannot capture `{name}`: it is a `var` and may change",
                                   span, hint=f"capture a snapshot: `let {name}_now = {name}` before the lambda, "
                                              f"and use `{name}_now` inside it")
                return

    def declare(self, name, t, mutable, span, kind, kw_span=None):
        if name == "_":
            return
        prev = self.lookup(name)
        if kind == "newtype_value":
            pass            # the `value` of a newtype's constructor: the name is fixed by the language
        elif prev is not None or name in self.fns or name in self.globals or name in self.consts:
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
                      hint=snake_hint(name))
        self.scopes[-1][name] = Var(t, mutable, span, kind, kw_span)

    # ---- functions, constants & tests --------------------------------------------
    def check_const(self, d: N.ConstDecl):
        t = self.consts.get(d.name)
        if t is None or not any(c is d for c in self.own_consts):   # (a duplicate was reported in collect)
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
        sig = self.methods.get(d.name) if d.owner_kind else self.fns.get(d.name)
        if sig is None or sig.decl is not d:
            return
        self.tparams = {t: TParam(t) for t in d.type_params}
        if getattr(sig, "self_type", None) is not None:
            self.tparams["Self"] = sig.self_type
        self.bounds = {t: set(v) for t, v in sig.bounds.items()}
        self.scopes = []
        self.push()
        for (pname, pt), p in zip(sig.params, d.params):
            # a trait fixes the parameters of its methods: unused ones are not a smell there
            self.declare(pname, pt, False, p.span, "newtype_value" if d.constructs else
                         "method_param" if d.owner_kind else "param")
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
        self.bounds = {}
        self.scopes = []
        self.push()
        self.ctx = Ctx(f'test "{d.name}"', UNIT, {"io"}, is_test=True, purpose="test")
        self.block(d.body)
        self.pop()
        self.ctx = None

    def check_property(self, d: N.PropertyDecl):
        self.tparams = {}
        self.bounds = {}
        self.scopes = []
        self.push()
        d.param_types = []
        for p in d.params:
            t = self.resolve(p.type, {})
            if not self.generatable(t, set()):
                self.error("E0605", f"cannot generate random values of type `{show(t)}` for property input `{p.name}`",
                           p.span, hint="property inputs may be Int, Float, Bool, Str, Unit, List, Map, Option, "
                                        "Result and records/enums built from them (not newtypes with `requires`)")
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
        if isinstance(info, RecordInfo) and info.invariant:
            return False        # random values would break the invariant
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
        if s.mutable:
            freeze(t)
        self.declare(s.name, t, s.mutable, s.name_span, "var" if s.mutable else "let", s.kw_span)

    def s_Assign(self, s: N.Assign):
        v = self.lookup(s.name)
        if v is not None and v.mutable:
            self.captured_var(s.name, s.span, assigning=True)
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
            kind = {"param": "parameter", "method_param": "parameter", "for": "loop variable", "bind": "pattern variable",
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
        if isinstance(e, N.Call) and isinstance(e.callee, N.Name) and e.callee.name in ("fail", "todo", "exit"):
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
        elif he in self.records and self.records[he].newtype and show(self.newtype_value(ex)) == show(fo):
            hint = f"wrap the value: `{he}(value)`"
        elif hf in self.records and self.records[hf].newtype and show(self.newtype_value(fo)) == show(ex):
            hint = "read the wrapped value: `.value`"
        if isinstance(ex, TFn) and isinstance(fo, TFn) and eff_names(fo) - eff_names(ex):
            more = ", ".join(sorted(eff_names(fo) - eff_names(ex)))
            hint = (f"this function uses `{more}`, which `{show(ex)}` does not allow: add "
                    f"`uses {', '.join(sorted(eff_names(ex) | eff_names(fo)))}` to the function type")
        msg = f"expected `{show(ex)}`, found `{show(fo)}`"
        if what:
            msg = f"{what}: {msg}"
        self.error("E0202", msg, span, hint=hint, fix=fix)

    def newtype_value(self, t):
        """The type of the `value` of a newtype (`Id[User]` → its wrapped type)."""
        info = self.records[head(t)]
        return subst(info.fields.get("value", ANY), self.args_map(info, t))

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
            if self.holds_fn(kt, set()):
                self.error("E0202", f"map keys cannot contain functions, found `{show(kt)}`", en.key.span,
                           hint="keys are compared with `==`, which functions do not have")
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
            if v.mutable:
                self.captured_var(e.name, e.span)
            t = prune(v.type)
            if isinstance(t, TFn) and not v.mutable:
                # a function with fewer effects fits where more are allowed: each use may widen them
                return TFn(t.params, t.ret, flex(eprune(t.eff).names))
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
            mapping = {t: TVar() for t in sig.tparams}
            e.sig, e.inst = sig, mapping
            self.note_bounds(sig, mapping, e.span)
            # a function used as a value: calling the value does its effects
            return TFn([subst(t, mapping) for _, t in sig.params], subst(sig.ret, mapping), flex(sig.effects))
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
            elif self.holds_fn(lt, set()):
                self.error("E0211", "functions cannot be compared", e.span,
                           hint=None if isinstance(prune(lt), TFn) else f"`{show(prune(lt))}` contains functions")
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
        self.need_effects(f"`{sig.name}`", sig.effects, span)

    def need_effects(self, what, effects, span):
        """Calling `what` (a quoted name, or a description) does `effects`: the current function must declare
        them."""
        self.ctx.used |= set(effects) & self.ctx.effects   # a missing effect is reported here, not again later
        missing = set(effects) - self.ctx.effects
        if not missing:
            return
        effs = ", ".join(sorted(missing))
        purpose = self.ctx.purpose
        if purpose in ("contract", "const"):
            kind = "contracts" if purpose == "contract" else "constants"
            self.error("E0401", f"{kind} must be pure, but {what} uses `{effs}`", span)
        elif purpose == "parallel":
            self.error("E0401", f"`par_map` runs this function in worker processes, so it must be pure, but "
                                f"{what} uses `{effs}`", span,
                       hint="compute the values with `par_map`, then do the effects with the results")
        elif purpose == "fntype":
            self.error("E0401", f"calling {what} requires effect `{effs}`, but the function type "
                                f"`{show(self.ctx.fn_type)}` does not declare it", span,
                       hint=f"add `uses {', '.join(sorted(eff_names(self.ctx.fn_type) | missing))}` to the function type")
        elif purpose == "test" or self.ctx.is_test:
            self.error("E0401", f"tests may only use `io`, but {what} uses `{effs}`", span,
                       hint="pass the time/random/file value as a parameter so the code under test stays deterministic")
        else:
            fix = None
            allowed = sorted(self.ctx.effects | missing)
            if self.ctx.sig_end is not None and not self.ctx.effects:
                se = self.ctx.sig_end
                fix = {"span": Span(se.file, se.end_line, se.end_col, se.end_line, se.end_col),
                       "text": " uses " + ", ".join(allowed)}
            self.error("E0401", f"calling {what} requires effect `{effs}`, but `{self.ctx.name}` "
                                f"does not declare it", span,
                       hint=f"add `uses {', '.join(allowed)}` to the signature of `{self.ctx.name}`", fix=fix)

    def call_sig(self, sig, args, span, expected=None, self_type=None, display=None, node=None, poly=True):
        display = display or sig.name
        mapping = {t: TVar(t) for t in sig.tparams}
        if node is not None:
            node.sig, node.inst = sig, mapping
        self.note_bounds(sig, mapping, span)
        params = [(n, subst(t, mapping)) for n, t in sig.params]
        ret = subst(sig.ret, mapping)
        if self_type is not None:
            if not params or not unify(params[0][1], self_type):
                need = show(params[0][1]) if params else "?"
                alt = None
                for name, other in BUILTIN_METHODS.get(head(self_type), {}).items():
                    if name != display and name.startswith(display) and other.params and \
                            unify(subst(other.params[0][1], {t: TVar() for t in other.tparams}), self_type):
                        alt = name
                        break
                self.error("E0204", f"method `{display}` needs a receiver of type `{need}`, found `{show(self_type)}`",
                           span, hint=f"use `.{alt}()` for `{show(self_type)}`" if alt else None)
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
        if poly:
            self.poly_effects(sig, params, assigned, display)
        return ret

    def poly_effects(self, sig, params, assigned, display):
        """A built-in that takes a function (`map`, `filter`, ...) does what the function does."""
        orig = dict(sig.params)
        for n, t in params:
            o = prune(orig.get(n))
            if n in assigned and isinstance(o, TFn) and o.eff.poly:
                f = assigned[n].value
                what = f"`{f.name}`" if isinstance(f, N.Name) else f"the function passed to `{display}`"
                self.need_effects(what, eff_names(t), f.span)

    def call_fn_type(self, ft, args, span, what="this function"):
        ft = prune(ft)
        if ft is ANY:
            for a in args:
                self.expr(a.value)
            return ANY
        if isinstance(ft, TVar):
            ps = [prune(self.expr(a.value)) for a in args]
            r = TVar()
            unify(ft, TFn(ps, r))   # a function of unknown type is called as a pure one
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
        self.need_effects(what, eff_names(ft), span)
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
                    owners = [tr for tr, info in self.traits.items() if c.name in info.methods]
                    if owners:
                        hint, fix = (f"`{c.name}` is a method of trait `{owners[0]}`: call it on the value, "
                                     f"`x.{c.name}(...)`"), None
                    elif c.name in special:
                        hint, fix = special[c.name], None
                    else:
                        hint, fix = self.did_you_mean(c.name, self.visible_names(), c.span)
                    self.error("E0201", f"unknown function `{c.name}`", c.span, hint=hint, fix=fix)
                for a in e.args:
                    self.expr(a.value)
                return ANY
            v.used = True
            return self.call_fn_type(v.type, e.args, e.span, what=f"`{c.name}`")
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
                return self.call_fn_type(ft, e.args, e.span, what=f"`{m}`")
        if isinstance(rt, TVar):
            self.error("E0214", f"cannot infer the type of this value before calling `.{m}()`", e.obj.span,
                       hint="add a type annotation, e.g. `let xs: List[Int] = []`")
            for a in e.args:
                self.expr(a.value)
            return ANY
        bsig = BUILTIN_METHODS.get(h, {}).get(m) if h else None
        if bsig is not None:
            e.resolved = ("builtin", h, m)
            if h == "List" and m == "par_map":
                return self.par_map_call(bsig, rt, e, exp)
            return self.call_sig(bsig, e.args, e.span, expected=exp, self_type=rt, display=m, node=e)
        if isinstance(rt, TParam):
            found = [tr for tr in sorted(self.bounds.get(rt.name, ())) if m in self.traits[tr].methods]
            if found:
                if len(found) > 1:
                    self.error("E0204", f"`{m}` is a method of both `{found[0]}` and `{found[1]}`", e.method_span,
                               hint="rename the method in one of the traits")
                e.resolved = ("trait", found[0], m)
                return self.call_sig(self.traits[found[0]].methods[m], e.args, e.span, expected=exp, self_type=rt,
                                     display=m, node=e)
        tm = self.universe.type_methods.get(h, {}).get(m) if h else None
        if tm is not None and tm[0] in self.visible:
            e.resolved = ("ufcs", tm[1].module, tm[1].name)
            return self.call_sig(tm[1], e.args, e.span, expected=exp, self_type=rt, display=m, node=e)
        usig = self.fns.get(m)
        if usig is not None and usig.params:
            first = subst(usig.params[0][1], {t: TVar() for t in usig.tparams})
            if unify(first, rt):
                e.resolved = ("ufcs", usig.module, usig.name)
                return self.call_sig(usig, e.args, e.span, expected=exp, self_type=rt, display=m, node=e)
        if tm is not None:
            trait = tm[0]
            self.error("E0104", f"method `{m}` of `{h}` comes from trait `{trait}`, which is not imported here",
                       e.method_span, hint=f"add `use {self.traits[trait].module}.{{{trait}}}` at the top of the file")
            for a in e.args:
                self.expr(a.value)
            return ANY
        # error: unknown method
        cands = set(BUILTIN_METHODS.get(h, {})) | {"to_str"} | set(self.universe.type_methods.get(h, {}))
        if isinstance(rt, TParam):
            for tr in self.bounds.get(rt.name, ()):
                cands |= set(self.traits[tr].methods)
            having = [tr for tr, info in self.traits.items() if m in info.methods and tr in self.visible]
            if having:
                self.error("E0204", f"type parameter `{rt.name}` has no method `{m}`", e.method_span,
                           hint=f"`{m}` belongs to trait `{having[0]}`: declare the bound `[{rt.name}: {having[0]}]`")
                for a in e.args:
                    self.expr(a.value)
                return ANY
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

    def par_map_call(self, bsig, rt, e, exp):
        """`xs.par_map(f)` runs `f` in worker processes: it must be pure (a lambda checked without effects, or a
        function value whose type has no `uses`), and the values it returns must not contain functions."""
        f = e.args[0].value if len(e.args) == 1 else None
        if isinstance(f, N.Lambda):
            self.pure_lambda = f
        t = self.call_sig(bsig, e.args, e.span, expected=exp, self_type=rt, display="par_map", node=e, poly=False)
        self.pure_lambda = None
        if f is not None and not isinstance(f, N.Lambda):
            effs = ", ".join(sorted(eff_names(getattr(f, "kt", None) or ANY)))
            if effs:
                what = f"`{f.name}`" if isinstance(f, N.Name) else "this function"
                self.error("E0406", f"`par_map` runs {what} in worker processes, so it must be pure, but "
                                    f"{what} uses `{effs}`", f.span,
                           hint="compute the values with `par_map`, then do the effects with the results")
        r = prune(t)
        if isinstance(r, TCon) and r.args and self.holds_fn(r.args[0], set()):
            self.error("E0406", f"the results of `par_map` are sent between processes, so they cannot contain "
                                f"functions (`{show(r.args[0])}`)", e.span)
        return t

    def holds_fn(self, t, seen):
        t = prune(t)
        if isinstance(t, TFn):
            return True
        if not isinstance(t, TCon) or show(t) in seen:
            return False
        seen.add(show(t))
        if any(self.holds_fn(a, seen) for a in t.args):
            return True
        if t.name in self.records:
            info = self.records[t.name]
            m = self.args_map(info, t)
            return any(self.holds_fn(subst(ft, m), seen) for ft in info.fields.values())
        if t.name in self.enums:
            info = self.enums[t.name]
            m = self.args_map(info, t)
            return any(self.holds_fn(subst(ft, m), seen) for fs in info.variants.values() for _, ft in fs)
        return False

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
        if info.newtype and not (self.ctx is not None and self.ctx.name == name):
            self.error("E0217", f"`{name}` is a newtype: construct it with `{name}(...)`", e.span,
                       hint="a newtype is built only by its constructor, which checks the type's `requires`")
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
        if info.newtype:
            self.error("E0217", f"`with` cannot change a newtype (`{h}`)", e.span,
                       hint=f"build a new value with its constructor: `{h}(...)`")
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
        purpose = outer.purpose if outer.purpose in ("test", "contract", "const", "parallel") else "lambda"
        effects = outer.effects
        fixed = efn is not None and eprune(efn.eff).fixed
        if getattr(self, "pure_lambda", None) is e:
            purpose, effects = "parallel", set()
            self.pure_lambda = None
        elif fixed:
            # the lambda must fit a written function type: it may do exactly the effects that type declares
            purpose, effects = "fntype", set(eprune(efn.eff).names)
        e.ptypes, e.ret_t = ptypes, ret
        self.ctx = Ctx(outer.name, ret, effects, purpose=purpose, sig_end=outer.sig_end)
        if fixed:
            self.ctx.fn_type = efn
        self.ctx.is_test = False
        if not hasattr(self, "lambda_bounds"):
            self.lambda_bounds = []
            self.lambda_serial = 0
        self.lambda_serial += 1
        self.lambda_bounds.append((len(self.scopes), self.lambda_serial))
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
        self.lambda_bounds.pop()
        used = self.ctx.used
        self.ctx = outer
        return TFn(ptypes, ret, flex(used))

    # ---- match -----------------------------------------------------------------
    def e_Match(self, e, exp):
        st = prune(self.expr(e.subject))
        result = TVar()
        if exp is not None:
            unify(result, exp)
        rows = []          # unguarded arms seen so far, as pattern vectors for the usefulness check
        for arm in e.arms:
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
            vec = [self.norm_pattern(arm.pattern)]
            if rows and useful(rows, vec, [st], self.ctors_of) is None:
                self.warn("W0303", "unreachable match arm: the arms above already cover every value it matches",
                          arm.pattern.span, hint="remove it or move it above the arm that covers it")
            if arm.guard is None:   # guarded arms never count for exhaustiveness
                rows.append(vec)
        self.exhaustive(st, rows, e)
        return result

    # ---- exhaustiveness (usefulness algorithm, Maranget 2007) ------------------------------------
    def norm_pattern(self, p):
        if isinstance(p, N.PLit):
            if isinstance(p.value, bool):
                return ("true" if p.value else "false", [])
            return (f"lit:{p.value!r}", [])
        if isinstance(p, N.PVariant):
            return (p.variant, [self.norm_pattern(a) for a in p.args])
        return WILD

    def ctors_of(self, t):
        """{constructor: [field types]} for a type with finitely many constructors, else None."""
        t = prune(t)
        h = head(t)
        if h == "Bool":
            return {"true": [], "false": []}
        if h == "Option":
            return {"Some": [t.args[0]], "None": []}
        if h == "Result":
            return {"Ok": [t.args[0]], "Err": [t.args[1]]}
        if h in self.enums:
            info = self.enums[h]
            m = self.args_map(info, t)
            return {v: [subst(ft, m) for _, ft in fs] for v, fs in info.variants.items()}
        return None

    def render_pattern(self, p, t, top=False):
        if p is WILD:
            return "_"
        name, args = p
        t = prune(t)
        h = head(t)
        if name in ("true", "false", "None"):
            return name
        fields = (self.ctors_of(t) or {}).get(name, [])
        if h in self.enums:
            names = [f for f, _ in self.enums[h].variants.get(name, [])]
            if not args:
                return f"{h}.{name}"
            if top and all(a is WILD for a in args):
                return f"{h}.{name}({', '.join(names)})"
            return f"{h}.{name}({', '.join(self.render_pattern(a, ft) for a, ft in zip(args, fields))})"
        if top and all(a is WILD for a in args):
            return {"Some": "Some(value)", "Ok": "Ok(value)", "Err": "Err(error)"}.get(name, name)
        return f"{name}({', '.join(self.render_pattern(a, ft) for a, ft in zip(args, fields))})"

    def exhaustive(self, st, rows, e):
        st = prune(st)
        if st is ANY or isinstance(st, TVar):
            return
        missing = []
        rows = list(rows)
        while len(missing) < 6:
            w = useful(rows, [WILD], [st], self.ctors_of)
            if w is None:
                break
            if w[0] is WILD:
                if not missing:
                    self.error("E0301", f"match on `{show(st)}` needs a catch-all arm", e.span,
                               hint="add `_ => ...` as the last arm")
                    return
                break
            missing.append(w[0])
            rows.append([w[0]])
        if missing:
            arms = ", ".join(f"`{self.render_pattern(w, st, top=True)} => ...`" for w in missing)
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
    def all_public(self):
        """The prelude and the runtime export everything; other modules only their `pub` declarations."""
        return self.sys or self.module == "prelude"

    def private_decl(self, name):
        """The declaration of `name` if this module declares it without `pub` (for a precise import error)."""
        if self.all_public():
            return None
        for d in self.program.decls:
            if isinstance(d, (N.FnDecl, N.ConstDecl, N.TypeDecl, N.EnumDecl, N.AliasDecl, N.TraitDecl)) and \
                    d.name == name and not d.public and not getattr(d, "owner_kind", None):
                return d
        return None

    def exports(self):
        """The importable names: `pub` declarations (everything in the prelude and the runtime)."""
        out = {}
        everything = self.all_public()
        for d in self.program.decls:
            if not everything and not getattr(d, "public", False):
                continue
            if isinstance(d, N.FnDecl) and isinstance(self.fns.get(d.name), Sig) and self.fns[d.name].decl is d:
                out[d.name] = ("fn", self.fns[d.name])
            elif isinstance(d, N.ConstDecl) and d.name in self.consts:
                out[d.name] = ("const", self.consts[d.name])
            elif isinstance(d, (N.TypeDecl, N.EnumDecl, N.AliasDecl, N.TraitDecl)) and \
                    self.universe.owner(d.name) == self.module:
                out[d.name] = ("type", d.name)
        return out


WILD = None   # the wildcard in normalized patterns; a constructor is (name, [sub-patterns])


def useful(rows, q, types, ctors_of):
    """Is pattern vector `q` useful w.r.t. `rows` (does it match a value no row matches)? Returns a witness
    vector of patterns (WILD or (ctor, args)) for such a value, or None."""
    if not q:
        return None if rows else []
    t, rest_t = types[0], types[1:]
    head_p = q[0]
    all_ctors = ctors_of(t)

    def specialize(c, arity):
        out = []
        for r in rows:
            p = r[0]
            if p is WILD:
                out.append([WILD] * arity + r[1:])
            elif p[0] == c:
                args = (list(p[1]) + [WILD] * arity)[:arity]
                out.append(args + r[1:])
        return out

    def field_types(c, arity):
        fts = (all_ctors or {}).get(c)
        return list(fts) if fts is not None and len(fts) == arity else [ANY] * arity

    if head_p is not WILD:
        c, args = head_p
        k = len(args)
        w = useful(specialize(c, k), list(args) + q[1:], field_types(c, k) + rest_t, ctors_of)
        return None if w is None else [(c, w[:k])] + w[k:]
    used = {r[0][0] for r in rows if r[0] is not WILD}
    if all_ctors is not None and used >= set(all_ctors):
        for c, fts in all_ctors.items():
            k = len(fts)
            w = useful(specialize(c, k), [WILD] * k + q[1:], list(fts) + rest_t, ctors_of)
            if w is not None:
                return [(c, w[:k])] + w[k:]
        return None
    w = useful([r[1:] for r in rows if r[0] is WILD], q[1:], rest_t, ctors_of)
    if w is None:
        return None
    if all_ctors is None or not used:
        return [WILD] + w
    c = next(c for c in all_ctors if c not in used)
    return [(c, [WILD] * len(all_ctors[c]))] + w


def is_lit(e):
    """Integer literal arithmetic (typed as Word or Int by context in system modules)."""
    if isinstance(e, N.IntLit):
        return True
    if isinstance(e, N.Binary) and e.op in ("+", "-", "*", "/", "%"):
        return is_lit(e.left) and is_lit(e.right)
    if isinstance(e, N.Unary) and e.op == "-":
        return is_lit(e.operand)
    return False


def snake_hint(name):
    s = to_snake(name)
    return "names use ASCII letters, digits and `_`" if s == name else f"rename it to `{s}`"


def to_snake(name):
    s = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
    return s.replace("__", "_")
