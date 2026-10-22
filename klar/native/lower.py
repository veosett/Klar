"""Typed AST -> KIR.

* Monomorphization: every generic function is instantiated per concrete type list.
* Uniform 64-bit values (see kir.py); records, enums, strings, lists, maps and
  closures are heap objects  [rc][type-descriptor][payload...].
* Reference counting: parameters are *borrowed* unless the function consumes them (own.py), results are
  *owned*; locals own their values; temporaries are released right after use.  Because Klar values are
  immutable there are no cycles, so reference counting frees everything.
* Reuse: the last use of a local moves its value (own.py): `x = x.push(v)`, `w = f(w)`,
  `w with { f: w.f.set(k, v) }` update unique objects in place, across function calls.

Runtime services are ordinary Klar functions in klar/rt/*.klar (system Klar).
"""
import struct

from .. import nodes as N
from ..builtins import GLOBALS, METHODS, parsed
from ..types import NEVER, TCon, TFn, TParam, prune, show
from .intrinsics import SYS_NAMES
from .kir import Fn
from .own import EMPTY, REUSE, Liveness, infer_owned, path_of, root_of

K_UNIT, K_BOOL, K_INT, K_FLOAT, K_WORD = 0, 1, 2, 3, 4
K_STR, K_LIST, K_MAP, K_RECORD, K_ENUM, K_FN, K_BIG, K_BUF, K_BYTES = 10, 11, 12, 13, 14, 15, 16, 17, 18

UNIT_T = TCon("Unit")
INT_T = TCon("Int")
STR_T = TCon("Str")
BOOL_T = TCon("Bool")
FLOAT_T = TCon("Float")
WORD_T = TCon("Word")



class NativeUnsupported(Exception):
    pass


def zonk(t, env):
    t = prune(t)
    if isinstance(t, TParam):
        if t.name not in env:
            raise NativeUnsupported(f"unbound type parameter {t.name}")
        return env[t.name]
    if isinstance(t, TCon):
        return TCon(t.name, [zonk(a, env) for a in t.args]) if t.args else t
    if isinstance(t, TFn):
        return TFn([zonk(p, env) for p in t.params], zonk(t.ret, env))
    if t is NEVER:
        return UNIT_T
    return UNIT_T          # unconstrained type variable / error type: a value is never inspected


def rck(t):
    h = t.name if isinstance(t, TCon) else None
    if h == "Int":
        return "int"
    if h in ("Float", "Bool", "Unit", "Word") or h is None and not isinstance(t, TFn):
        return None
    return "obj"


def fnv1a(text):
    """32-bit FNV-1a of the UTF-8 text: a stable short name for a type (unlike `hash`, the same in every run)."""
    h = 2166136261
    for b in text.encode("utf-8"):
        h = ((h ^ b) * 16777619) & 0xFFFFFFFF
    return h


def tag_int(n):
    return (n << 1) | 1


class V:
    __slots__ = ("reg", "t", "owned")

    def __init__(self, reg, t, owned):
        self.reg = reg
        self.t = t
        self.owned = owned


class Local:
    __slots__ = ("reg", "t", "owned", "box")

    def __init__(self, reg, t, owned, box=False):
        self.reg = reg
        self.t = t
        self.owned = owned
        self.box = box


# ===========================================================================
# program-level state: instances, data, type descriptors
# ===========================================================================
class Program:
    def __init__(self, loaded, image):
        self.loaded = loaded
        self.universe = loaded.universe
        self.img = image
        self.fns = []
        self.instances = {}
        self.queue = []
        self.strings = {}
        self.spans = {}
        self.tds = {}
        self.static_objs = {}
        self.const_slots = {}
        self.counter = 0
        self.rt = {}                      # runtime function name -> (module, decl)
        for m in getattr(loaded, "runtime", []):
            for d in m.program.decls:
                if isinstance(d, N.FnDecl):
                    self.rt[d.name] = (m, d)
        self.modules_by_name = {m.name: m for m in loaded.modules}
        for m in getattr(loaded, "runtime", []):
            self.modules_by_name[m.name] = m
        self.owned = infer_owned([d for m in loaded.modules if not m.is_sys for d in m.program.decls
                                  if isinstance(d, N.FnDecl) and d.body is not None])

    def owned_of(self, decl):
        """Indices of the parameters `decl` consumes (passed owned)."""
        return self.owned.get(id(decl), EMPTY)

    def uid(self, prefix):
        self.counter += 1
        return f"{prefix}{self.counter}"

    # ---- data -----------------------------------------------------------------
    def words(self, name, ws, absolute=()):
        """Emit data words; entries given as (symbol, addend) tuples become absolute addresses."""
        payload = bytearray()
        rel = []
        for i, w in enumerate(ws):
            if isinstance(w, tuple):
                rel.append((i * 8, w[0], w[1]))
                payload += b"\0" * 8
            else:
                payload += struct.pack("<q", w if w < 2 ** 63 else w - 2 ** 64)
        self.img.add_data(name, payload)
        base = self.img.data_syms[name]
        for off, sym, add in rel:
            self.img.data_abs.append((base + off, sym, add))
        return name

    def str_obj(self, text):
        """Immortal static Str object for a literal."""
        if text in self.strings:
            return self.strings[text]
        name = f"str{len(self.strings)}"
        raw = text.encode("utf-8")
        payload = struct.pack("<qq", -1, 0) + struct.pack("<qq", len(raw), len(text)) + raw + b"\0"
        self.img.add_data(name, payload)
        base = self.img.data_syms[name]
        self.img.data_abs.append((base + 8, "td_Str", 0))
        self.strings[text] = name
        return name

    def span_sym(self, span):
        key = (span.file, span.line, span.col, span.end_line, span.end_col)
        if key in self.spans:
            return self.spans[key]
        src = self.loaded.sources.get(span.file, "").split("\n")
        text = src[span.line - 1].rstrip("\r") if 0 < span.line <= len(src) else ""
        name = f"span{len(self.spans)}"
        self.words(name, [(self.str_obj(span.file), 0), span.line, span.col, span.end_line, span.end_col,
                          (self.str_obj(text), 0)])
        self.spans[key] = name
        return name

    # ---- type descriptors ---------------------------------------------------------
    def td(self, t):
        key = show(t)
        if key in self.tds:
            return self.tds[key]
        name = f"td{len(self.tds)}"
        self.tds[key] = name
        h = t.name if isinstance(t, TCon) else None
        prim = {"Unit": K_UNIT, "Bool": K_BOOL, "Int": K_INT, "Float": K_FLOAT, "Word": K_WORD, "Str": K_STR,
                "Bytes": K_BYTES}
        if isinstance(t, TFn):
            self.words(name, [K_FN, (self.str_obj("fn"), 0), 0, 0, 0, 0])
        elif h in prim:
            self.words(name, [prim[h], (self.str_obj(h), 0), 0, 0, 0, 0])
        elif h == "List":
            self.words(name, [K_LIST, (self.str_obj("List"), 0), (self.td(t.args[0]), 0), 0, 0, 0])
        elif h == "Map":
            self.words(name, [K_MAP, (self.str_obj("Map"), 0), (self.td(t.args[0]), 0), (self.td(t.args[1]), 0), 0, 0])
        elif h in ("Option", "Result"):
            if h == "Option":
                variants = [("None", [], []), ("Some", [t.args[0]], ["value"])]
            else:
                variants = [("Ok", [t.args[0]], ["value"]), ("Err", [t.args[1]], ["error"])]
            self.enum_td(name, h, variants, style=1)
        elif h in self.universe.records:
            info = self.universe.records[h]
            m = dict(zip(info.tparams, t.args))
            fts = [zonk(ft, m) for ft in info.fields.values()]
            ftab = self.words(name + "_f", [(self.td(ft), 0) for ft in fts] or [0])
            ntab = self.words(name + "_n", [(self.str_obj(f), 0) for f in info.fields] or [0])
            self.words(name, [K_RECORD, (self.str_obj(h), 0), len(fts), (ftab, 0), (ntab, 0), 0])
        elif h in self.universe.enums:
            info = self.universe.enums[h]
            m = dict(zip(info.tparams, t.args))
            variants = [(v, [zonk(ft, m) for _, ft in fs], [f for f, _ in fs]) for v, fs in info.variants.items()]
            self.enum_td(name, h, variants, style=0)
        else:
            raise NativeUnsupported(f"no type descriptor for {key}")
        return name

    def enum_td(self, name, enum_name, variants, style):
        rows = []
        for i, (vname, ftypes, fnames) in enumerate(variants):
            ftab = self.words(f"{name}_v{i}f", [(self.td(ft), 0) for ft in ftypes] or [0])
            ntab = self.words(f"{name}_v{i}n", [(self.str_obj(f), 0) for f in fnames] or [0])
            rows += [(self.str_obj(vname), 0), len(ftypes), (ftab, 0), (ntab, 0)]
        vtab = self.words(name + "_vars", rows)
        self.words(name, [K_ENUM, (self.str_obj(enum_name), 0), len(variants), (vtab, 0), style, 0])

    def closure_td(self, cap_types):
        name = self.uid("tdc")
        ctab = self.words(name + "_c", [(self.td(t), 0) for t in cap_types] or [0])
        self.words(name, [K_FN, (self.str_obj("fn"), 0), len(cap_types), (ctab, 0), 0, 0])
        return name

    def static_variant(self, t, tag):
        """Immortal object for a field-less variant (None, Color.Red, Tree.Leaf ...)."""
        key = (show(t), tag)
        if key not in self.static_objs:
            name = f"obj{len(self.static_objs)}"
            self.words(name, [-1, (self.td(t), 0), tag])
            self.static_objs[key] = name
        return self.static_objs[key]

    def variant_index(self, t, vname):
        h = t.name
        if h == "Option":
            return ["None", "Some"].index(vname)
        if h == "Result":
            return ["Ok", "Err"].index(vname)
        return list(self.universe.enums[h].variants).index(vname)

    def variant_fields(self, t, vname):
        h = t.name
        if h == "Option":
            return [t.args[0]] if vname == "Some" else []
        if h == "Result":
            return [t.args[0]] if vname == "Ok" else [t.args[1]]
        info = self.universe.enums[h]
        m = dict(zip(info.tparams, t.args))
        return [zonk(ft, m) for _, ft in info.variants[vname]]

    def record_fields(self, t):
        info = self.universe.records[t.name]
        m = dict(zip(info.tparams, t.args))
        return [(f, zonk(ft, m)) for f, ft in info.fields.items()]

    # ---- instances ---------------------------------------------------------------
    def instance(self, module, decl, type_args, kind="user"):
        key = (module.name, decl.name, tuple(show(t) for t in type_args))
        if key in self.instances:
            return self.instances[key]
        suffix = "" if not type_args else "_" + "_".join(str(fnv1a(show(t)) % 100000) for t in type_args)
        name = f"k_{module.name.replace('.', '_')}__{decl.name}{suffix}"
        while any(name == v for v in self.instances.values()):
            name += "_"
        self.instances[key] = name
        self.queue.append((name, module, decl, dict(zip(decl.type_params, type_args)), kind))
        return name

    def rt_fn(self, name):
        if name not in self.rt:
            raise NativeUnsupported(f"runtime function {name} is not implemented")
        m, d = self.rt[name]
        return self.instance(m, d, [], kind="rt"), d

    def run(self):
        while self.queue:
            name, module, decl, env, kind = self.queue.pop()
            FnLowering(self, module, env, kind == "rt").function(name, decl)

    def const_slot(self, module_name, cname):
        key = (module_name, cname)
        if key not in self.const_slots:
            sym = f"const{len(self.const_slots)}"
            self.img.add_bss(sym, 8)
            self.const_slots[key] = sym
        return self.const_slots[key]


# ===========================================================================
# function bodies
# ===========================================================================
class Exit(Exception):
    pass


class FnLowering:
    def __init__(self, prog: Program, module, env, is_rt):
        self.p = prog
        self.m = module
        self.env = env
        self.is_rt = is_rt
        self.fn = None
        self.scopes = []
        self.loops = []
        self.ret_t = UNIT_T
        self.dead = False
        self.closure_self = None
        self.captures = {}
        self.cand = set()         # uses that may move their value (own.Liveness)
        self.bound = {}           # path -> register of the unique record a `with` is updating in place
        self.takeable = set()     # field uses inside such a `with` that take the field out of it

    def locals_of(self, params, body):
        names = list(params)
        for n in N.walk(body):
            if isinstance(n, N.Let):
                names.append(n.name)
            elif isinstance(n, N.For):
                names.append(n.var)
        return names

    # ---- small helpers ----------------------------------------------------------
    def ty(self, node):
        t = getattr(node, "kt", None)
        if t is None:
            raise NativeUnsupported(f"missing type for {type(node).__name__} at {node.span.short()}")
        return zonk(t, self.env)

    def emit(self, *ins):
        if not self.dead:
            self.fn.emit(*ins)

    def reg(self):
        return self.fn.reg()

    def const(self, imm):
        r = self.reg()
        self.emit("const", r, imm)
        return r

    def label(self, hint="L"):
        return self.fn.label(hint)

    def place(self, lab):
        self.fn.emit("label", lab)
        self.dead = False

    def jump(self, lab):
        self.emit("jmp", lab)
        self.dead = True

    def call(self, target, args, result=True):
        d = self.reg() if result else None
        self.emit("call", d, target, list(args))
        return d

    def call_rt(self, name, args):
        target, _ = self.p.rt_fn(name)
        return self.call(target, args)

    def addr(self, sym):
        r = self.reg()
        self.emit("addr", r, sym)
        return r

    def site(self, span):
        if not self.is_rt and span is not None:
            self.emit("site", self.p.span_sym(span))

    # ---- ownership ------------------------------------------------------------------
    def own(self, v):
        if not v.owned:
            k = rck(v.t)
            if k:
                self.emit("retain", k, v.reg)
        return v.reg

    def drop(self, v):
        if v is not None and v.owned:
            k = rck(v.t)
            if k:
                self.emit("release", k, v.reg)

    def owned_v(self, v):
        return V(self.own(v), v.t, True)

    # ---- moves (own.py) -------------------------------------------------------------
    def bound_prefix(self, path):
        """The longest path bound by an enclosing in-place `with` that `path` lies in, or None."""
        best = None
        for q in self.bound:
            if (path == q or path.startswith(q + ".")) and (best is None or len(q) > len(best)):
                best = q
        return best

    def moves(self, e):
        """Does consuming `e` move a value out of a variable or a record field (instead of copying)?"""
        if id(e) in self.takeable:
            return True
        if id(e) not in self.cand:
            return False
        p = path_of(e)
        if p is None or self.bound_prefix(p) is not None:
            return False
        loc = self.lookup(root_of(p))
        t = self.ty(e)
        if loc is None or not loc.owned or loc.box or rck(t) is None:
            return False
        # a field is taken out only when it can then be updated in place (a record or a collection)
        return "." not in p or (isinstance(e.obj, N.Name) and self.is_record(self.ty(e.obj)) and
                                (self.is_record(t) or getattr(t, "name", None) in ("List", "Map", "Bytes")))

    def is_record(self, t):
        return isinstance(t, TCon) and t.name in self.p.universe.records

    def field_off(self, t, name):
        return 16 + 8 * [f for f, _ in self.p.record_fields(t)].index(name)

    def cexpr(self, e):
        """An expression in a consuming position: a last use moves the value."""
        if not self.moves(e):
            return self.expr(e)
        t = self.ty(e)
        hole = self.addr("obj_None")         # immortal: releasing it does nothing
        if id(e) in self.takeable:           # a field of a record a `with` owns uniquely: take it out
            base = self.bound[path_of(e.obj)]
            off = self.field_off(self.ty(e.obj), e.name)
            r = self.reg()
            self.emit("load", r, base, off)
            self.emit("store", base, off, hole)
            return V(r, t, True)
        if isinstance(e, N.Name):            # the variable's last use: move its value out
            loc = self.lookup(e.name)
            r = self.reg()
            self.emit("mov", r, loc.reg)
            self.emit("mov", loc.reg, hole)
            return V(r, t, True)
        # `a.f`, the last use of a field of an owned record: take it out if the record is unique, else share it
        obj = self.lookup(e.obj.name).reg
        off = self.field_off(self.ty(e.obj), e.name)
        r = self.reg()
        self.emit("load", r, obj, off)
        rc, c = self.reg(), self.reg()
        self.emit("load", rc, obj, 0)
        self.emit("cmp", "eq", c, rc, self.const(1))
        steal, share, done = self.label("tk"), self.label("sh"), self.label("tkd")
        self.emit("br", c, steal, share)
        self.place(steal)
        self.emit("store", obj, off, hole)
        self.jump(done)
        self.place(share)
        self.emit("retain", rck(t), r)
        self.jump(done)
        self.place(done)
        return V(r, t, True)

    def bound_read(self, e):
        """A read of a path inside an in-place `with`: from the record being updated (borrowed)."""
        p = path_of(e)
        if p is None or not self.bound:
            return None
        q = self.bound_prefix(p)
        if q is None:
            return None
        r = self.bound[q]
        chain = []
        while path_of(e) != q:
            chain.append(e)
            e = e.obj
        cur_t = self.ty(e)
        for fa in reversed(chain):
            nr = self.reg()
            self.emit("load", nr, r, self.field_off(cur_t, fa.name))
            r, cur_t = nr, self.ty(fa)
        return V(r, cur_t, False)

    def unique_record(self, v):
        """An owned record value -> a register holding a unique copy (the value itself when it is unique)."""
        t = v.t
        u = self.reg()
        rc, c = self.reg(), self.reg()
        self.emit("load", rc, v.reg, 0)
        self.emit("cmp", "eq", c, rc, self.const(1))
        same, copy, done = self.label("uq"), self.label("cp"), self.label("uqd")
        self.emit("br", c, same, copy)
        self.place(copy)
        fields = self.p.record_fields(t)
        obj = self.call_rt("obj_new", [self.const(16 + 8 * len(fields)), self.addr(self.p.td(t))])
        for i, (_, ft) in enumerate(fields):
            r = self.reg()
            self.emit("load", r, v.reg, 16 + 8 * i)
            k = rck(ft)
            if k:
                self.emit("retain", k, r)
            self.emit("store", obj, 16 + 8 * i, r)
        self.emit("release", "obj", v.reg)
        self.emit("mov", u, obj)
        self.jump(done)
        self.place(same)
        self.emit("mov", u, v.reg)
        self.jump(done)
        self.place(done)
        return u

    def with_takes(self, e, bp):
        """The field uses inside `e` (a `with` updating the record at path bp in place) that may take their field out:
        the only use of that field, in a consuming position or as the base of a nested `with`."""
        occs = []

        def collect(x, bases):
            p = path_of(x)
            if p is not None:
                occs.append((p, x, bases))
                return
            if isinstance(x, N.Lambda):
                for n in N.walk(x.body):
                    if isinstance(n, N.Name):
                        occs.append((n.name, n, bases))
                return
            if isinstance(x, N.WithExpr):
                bp2 = path_of(x.base)
                collect(x.base, bases)
                inner = bases + (id(x.base),) if bp2 is not None else bases
                for f in x.fields:
                    collect(f.value, inner)
                return
            if isinstance(x, N.Node):
                for f in x.__dataclass_fields__:
                    v = getattr(x, f)
                    if isinstance(v, N.Node):
                        collect(v, bases)
                    elif isinstance(v, list):
                        for it in v:
                            if isinstance(it, N.Node):
                                collect(it, bases)
        for f in e.fields:
            collect(f.value, ())
        if any(bp == p or bp.startswith(p + ".") for p, _, _ in occs):
            return set()
        out = set()
        t = self.ty(e)
        for f in e.fields:
            if not rck(dict(self.p.record_fields(t))[f.name]):
                continue
            fp = bp + "." + f.name
            near = [o for o in occs if o[0] == fp or o[0].startswith(fp + ".") or fp.startswith(o[0] + ".")]
            exact = [o for o in near if o[0] == fp]
            if len(exact) == 1 and all(o is exact[0] or id(exact[0][1]) in o[2] for o in near):
                out.add(id(exact[0][1]))
        return out

    # ---- scopes -----------------------------------------------------------------
    def push_scope(self):
        self.scopes.append({"vars": {}, "clean": []})

    def pop_scope(self):
        sc = self.scopes.pop()
        self.cleanup([sc])

    def cleanup(self, scopes):
        for sc in reversed(scopes):
            for reg, kind in reversed(sc["clean"]):
                self.emit("release", kind, reg)

    def declare(self, name, reg, t, owned):
        sc = self.scopes[-1]
        sc["vars"][name] = Local(reg, t, owned)
        if owned:
            k = rck(t)
            if k:
                sc["clean"].append((reg, k))

    def lookup(self, name):
        for sc in reversed(self.scopes):
            if name in sc["vars"]:
                return sc["vars"][name]
        return None

    # ---- function ------------------------------------------------------------------
    def function(self, name, d: N.FnDecl):
        sig = self.m.checker.methods.get(d.name) if d.owner_kind else self.m.checker.fns.get(d.name)
        if self.is_rt and sig is None:
            sig = self.m.checker.fns[d.name]
        self.fn = Fn(name, len(d.params), d.name)
        self.p.fns.append(self.fn)
        self.ret_t = zonk(sig.ret, self.env)
        self.push_scope()
        owned = EMPTY if self.is_rt else self.p.owned_of(d)
        for i, (pname, pt) in enumerate(sig.params):
            self.declare(pname, i, zonk(pt, self.env), i in owned)
        if not self.is_rt:
            self.cand = Liveness(self.locals_of([p for p, _ in sig.params], d.body),
                                 {n.name for n in N.walk(d.ensures) if isinstance(n, N.Name)}).run_block(d.body)
            self.emit("enter", self.p.str_obj(d.name))
        self.decl = d
        for r in d.requires:
            self.contract(r, "R0002", "precondition", d)
        if d.ensures:
            self.ensures = d.ensures
        else:
            self.ensures = None
        self.block_body(d.body)
        if not self.dead:
            self.do_return(V(self.const(0), UNIT_T, True))

    def contract(self, cond, code, kind, d, result_local=None):
        c = self.expr(cond)
        ok = self.label("ok")
        bad = self.label("bad")
        self.emit("br", c.reg, ok, bad)
        self.place(bad)
        names = []
        for n in N.walk(cond):
            if isinstance(n, N.Name) and n.name not in names and self.lookup(n.name) is not None:
                names.append(n.name)
        details = self.details(names)
        msg = self.p.str_obj(f"{kind} `{self.src_text(cond.span)}` of `{d.name}` violated")
        self.call_rt("fail_with", [self.addr(self.p.str_obj(code)), self.addr(msg),
                                   self.addr(self.p.span_sym(cond.span)), details,
                                   self.addr(self.p.str_obj(
                                       "the caller passed arguments that the function does not accept"
                                       if code == "R0002" else
                                       "the function body returned a value that breaks its own contract"))])
        self.dead = True
        self.place(ok)

    def details(self, names):
        """List[Str] of `name = value` (built only on failure paths)."""
        lst = self.call_rt("list_new_str", [])
        for n in names:
            loc = self.lookup(n)
            v = self.read_local(n, loc)
            s = self.call_rt("show_to_str", [v.reg, self.addr(self.p.td(v.t))])
            lst = self.call_rt("detail_add", [lst, self.addr(self.p.str_obj(n)), s])
        return lst

    def src_text(self, span):
        lines = self.p.loaded.sources.get(span.file, "").split("\n")
        if span.line <= 0 or span.line > len(lines):
            return "?"
        line = lines[span.line - 1]
        return line[span.col - 1:span.end_col - 1] if span.line == span.end_line else line[span.col - 1:].strip()

    def do_return(self, v):
        r = self.own(v)
        if self.ensures:
            self.push_scope()
            self.declare("result", r, self.ret_t, False)
            for en in self.ensures:
                self.contract(en, "R0003", "postcondition", self.decl)
            self.scopes.pop()
        self.cleanup(self.scopes)
        if not self.is_rt:
            self.emit("leave")
        self.emit("ret", r)
        self.dead = True

    # ---- statements -----------------------------------------------------------------
    def block_body(self, block):
        self.push_scope()
        for s in block.stmts:
            self.stmt(s)
            if self.dead:
                break
        if self.dead:
            self.scopes.pop()
        else:
            self.pop_scope()

    def stmt(self, s):
        getattr(self, "s_" + type(s).__name__)(s)

    def s_Let(self, s):
        v = self.cexpr(s.value)
        if s.name == "_":
            self.drop(v)
            return
        r = self.own(v)
        reg = self.reg()
        self.emit("mov", reg, r)
        self.declare(s.name, reg, v.t, True)

    def s_Assign(self, s):
        loc = self.lookup(s.name)
        if loc is None:
            raise NativeUnsupported(f"assignment to non-local {s.name}")
        val = s.value
        k = rck(loc.t)
        # in-place reuse: x = x.push(...), x = x + "..."
        if isinstance(val, N.MethodCall) and isinstance(val.obj, N.Name) and val.obj.name == s.name and \
                getattr(val, "resolved", (None,))[0] == "builtin" and \
                (val.resolved[1], val.resolved[2]) in REUSE and \
                not any(isinstance(n, N.Name) and n.name == s.name for a in val.args for n in N.walk(a.value)):
            owner, m = val.resolved[1], val.resolved[2]
            new = self.builtin_method(val, owner, m, V(loc.reg, loc.t, True), consume=True)
            self.emit("mov", loc.reg, self.own(new))
            return
        if isinstance(val, N.Binary) and val.op == "+" and isinstance(val.left, N.Name) and \
                val.left.name == s.name and loc.t.name == "Str" and \
                not any(isinstance(n, N.Name) and n.name == s.name for n in N.walk(val.right)):
            rhs = self.expr(val.right)
            new = self.call_rt("Str_append_owned", [loc.reg, rhs.reg])
            self.drop(rhs)
            self.emit("mov", loc.reg, new)
            return
        v = self.cexpr(val)
        new = self.own(v)
        if k:
            self.emit("release", k, loc.reg)
        self.emit("mov", loc.reg, new)

    def s_Return(self, s):
        if s.value is None:
            self.do_return(V(self.const(0), UNIT_T, True))
            return
        self.do_return(self.cexpr(s.value))

    def s_ExprStmt(self, s):
        v = self.expr(s.expr)
        self.drop(v)

    def cond_branch(self, e, lt, lf):
        """Branch on a Bool expression without materializing `and` / `or` / `not` results."""
        if isinstance(e, N.Binary) and e.op in ("and", "or"):
            mid = self.label("sc")
            if e.op == "and":
                self.cond_branch(e.left, mid, lf)
            else:
                self.cond_branch(e.left, lt, mid)
            self.place(mid)
            self.cond_branch(e.right, lt, lf)
            return
        if isinstance(e, N.Unary) and e.op == "not":
            self.cond_branch(e.operand, lf, lt)
            return
        c = self.expr(e)
        self.emit("br", c.reg, lt, lf)

    def s_If(self, s):
        lt, lf, end = self.label("then"), self.label("else"), self.label("endif")
        self.cond_branch(s.cond, lt, lf)
        self.place(lt)
        self.block_body(s.then)
        self.jump(end)
        self.place(lf)
        if isinstance(s.else_, N.If):
            self.s_If(s.else_)
        elif s.else_ is not None:
            self.block_body(s.else_)
        self.jump(end)
        self.place(end)

    def s_While(self, s):
        top, body, end = self.label("wtop"), self.label("wbody"), self.label("wend")
        self.jump(top)
        self.place(top)
        self.cond_branch(s.cond, body, end)
        self.place(body)
        self.loops.append((end, top, len(self.scopes)))
        self.block_body(s.body)
        self.loops.pop()
        self.jump(top)
        self.place(end)

    def s_For(self, s):
        it = s.iter
        elem_t = zonk(s.elem_kt, self.env)
        top, body, step, end = self.label("ftop"), self.label("fbody"), self.label("fstep"), self.label("fend")
        if isinstance(it, N.Call) and isinstance(it.callee, N.Name) and it.callee.name == "range" and \
                self.lookup("range") is None and len(it.args) == 2 and not any(a.name for a in it.args):
            lo = self.expr(it.args[0].value)
            hi = self.expr(it.args[1].value)
            i = self.reg()
            self.emit("mov", i, self.own(lo))
            hi_r = self.own(hi)
            self.jump(top)
            self.place(top)
            c = self.reg()
            self.emit("icmp", "lt", c, i, hi_r)
            self.emit("br", c, body, end)
            self.place(body)
            self.push_scope()
            self.declare(s.var, i, INT_T, False)
            self.loops.append((end, step, len(self.scopes)))
            self.block_body(s.body)
            self.loops.pop()
            self.scopes.pop()
            self.jump(step)
            self.place(step)
            one = self.const(tag_int(1))
            self.emit("iop", "add", i, i, one, None)
            self.jump(top)
            self.place(end)
            self.emit("release", "int", i)
            self.emit("release", "int", hi_r)
            return
        lst = self.expr(it)
        lreg = self.own(lst)
        n = self.reg()
        self.emit("load", n, lreg, 16)
        data = self.reg()
        idx = self.const(0)
        self.jump(top)
        self.place(top)
        c = self.reg()
        self.emit("cmp", "lt", c, idx, n)
        self.emit("br", c, body, end)
        self.place(body)
        self.emit("load", data, lreg, 32)
        eight = self.const(8)
        off = self.reg()
        self.emit("bin", "mul", off, idx, eight)
        addr = self.reg()
        self.emit("bin", "add", addr, data, off)
        x = self.reg()
        self.emit("load", x, addr, 0)
        self.push_scope()
        self.declare(s.var, x, elem_t, False)
        self.loops.append((end, step, len(self.scopes)))
        self.block_body(s.body)
        self.loops.pop()
        self.scopes.pop()
        self.jump(step)
        self.place(step)
        one = self.const(1)
        self.emit("bin", "add", idx, idx, one)
        self.jump(top)
        self.place(end)
        self.emit("release", "obj", lreg)

    def s_Break(self, s):
        end, _, depth = self.loops[-1]
        self.cleanup(self.scopes[depth:])
        self.jump(end)

    def s_Continue(self, s):
        _, step, depth = self.loops[-1]
        self.cleanup(self.scopes[depth:])
        self.jump(step)

    def s_Assert(self, s):
        c = s.cond
        if isinstance(c, N.Binary) and c.op in ("==", "!=", "<", ">", "<=", ">="):
            lv = self.expr(c.left)
            rv = self.expr(c.right)
            ok = self.compare(c.op, lv, rv, c.span)
            good, bad = self.label("aok"), self.label("abad")
            self.emit("br", ok, good, bad)
            self.place(bad)
            lst = self.call_rt("list_new_str", [])
            ls = self.call_rt("show_to_str", [lv.reg, self.addr(self.p.td(lv.t))])
            lst = self.call_rt("detail_add", [lst, self.addr(self.p.str_obj("left")), ls])
            rs = self.call_rt("show_to_str", [rv.reg, self.addr(self.p.td(rv.t))])
            lst = self.call_rt("detail_add", [lst, self.addr(self.p.str_obj("right")), rs])
            self.assert_fail(s, c, lst)
            self.place(good)
            self.drop(lv)
            self.drop(rv)
            return
        v = self.expr(c)
        good, bad = self.label("aok"), self.label("abad")
        self.emit("br", v.reg, good, bad)
        self.place(bad)
        names = []
        for n in N.walk(c):
            if isinstance(n, N.Name) and n.name not in names and self.lookup(n.name) is not None:
                names.append(n.name)
        self.assert_fail(s, c, self.details(names))
        self.place(good)

    def assert_fail(self, s, c, details):
        msg = self.addr(self.p.str_obj(f"assertion failed: `{self.src_text(c.span)}`"))
        if s.message is not None:
            m = self.expr(s.message)
            sep = self.addr(self.p.str_obj(" — "))
            msg = self.call_rt("Str_concat", [msg, sep])
            msg = self.call_rt("Str_concat", [msg, m.reg])
        self.call_rt("fail_with", [self.addr(self.p.str_obj("R0005")), msg, self.addr(self.p.span_sym(s.span)),
                                   details, self.addr(self.p.str_obj(""))])
        self.dead = True

    # ---- expressions ------------------------------------------------------------------
    def expr(self, e):
        return getattr(self, "x_" + type(e).__name__)(e)

    def x_IntLit(self, e):
        t = self.ty(e)
        if t.name == "Word":
            return V(self.const(e.value), WORD_T, False)
        if -(2 ** 61) <= e.value < 2 ** 61:
            return V(self.const(tag_int(e.value)), INT_T, False)
        s = self.addr(self.p.str_obj(str(e.value)))
        return V(self.call_rt("int_parse_dec", [s]), INT_T, True)

    def x_FloatLit(self, e):
        bits = struct.unpack("<q", struct.pack("<d", e.value))[0]
        return V(self.const(bits), FLOAT_T, False)

    def x_BoolLit(self, e):
        return V(self.const(1 if e.value else 0), BOOL_T, False)

    def x_UnitLit(self, e):
        return V(self.const(0), UNIT_T, False)

    def x_StrLit(self, e):
        if all(isinstance(p, str) for p in e.parts):
            return V(self.addr(self.p.str_obj("".join(e.parts))), STR_T, False)
        sb = self.call_rt("sb_new", [])
        for p in e.parts:
            if isinstance(p, str):
                self.call_rt("sb_add_str", [sb, self.addr(self.p.str_obj(p))])
            else:
                v = self.expr(p)
                if v.t.name == "Int" and not v.t.args:
                    self.call_rt("int_show", [sb, v.reg])
                elif v.t.name == "Str" and not v.t.args:
                    self.call_rt("sb_add_str", [sb, v.reg])
                else:
                    self.call_rt("show_into", [sb, v.reg, self.addr(self.p.td(v.t)), self.const(1)])
                self.drop(v)
        return V(self.call_rt("sb_finish", [sb]), STR_T, True)

    def x_ListLit(self, e):
        t = self.ty(e)
        n = len(e.items)
        lst = self.call_rt("list_with_cap", [self.addr(self.p.td(t)), self.const(n)])
        data = self.reg()
        self.emit("load", data, lst, 32)
        for i, it in enumerate(e.items):
            v = self.cexpr(it)
            self.emit("store", data, 8 * i, self.own(v))
        self.emit("store", lst, 16, self.const(n))
        return V(lst, t, True)

    def x_MapLit(self, e):
        t = self.ty(e)
        mp = self.call_rt("map_new", [self.addr(self.p.td(t))])
        for en in e.entries:
            k = self.cexpr(en.key)
            v = self.cexpr(en.value)
            mp = self.call_rt("Map_set_owned", [mp, self.own(k), self.own(v)])
        return V(mp, t, True)

    def read_local(self, name, loc):
        if loc.box:
            r = self.reg()
            self.emit("load", r, loc.reg, 16)
            return V(r, loc.t, False)
        return V(loc.reg, loc.t, False)

    def x_Name(self, e):
        b = self.bound_read(e)
        if b is not None:
            return b
        loc = self.lookup(e.name)
        if loc is not None:
            return self.read_local(e.name, loc)
        if e.name in self.captures:
            idx, t = self.captures[e.name]
            r = self.reg()
            self.emit("load", r, self.closure_self, 24 + 8 * idx)
            return V(r, t, False)
        if e.name == "None":
            t = self.ty(e)
            return V(self.addr(self.p.static_variant(t, 0)), t, False)
        cmod, cname = self.resolve_const(e.name)
        if cmod is not None:
            r = self.reg()
            self.emit("load", r, self.addr(self.p.const_slot(cmod, cname)), 0)
            return V(r, self.ty(e), False)
        sig = getattr(e, "sig", None)
        if sig is not None and sig.decl is not None:
            return self.fn_value(e, sig)
        raise NativeUnsupported(f"name `{e.name}` as a value")

    def resolve_const(self, name):
        m = self.m
        if name in m.import_from and m.import_from[name][1] == "const":
            return m.import_from[name][0].name, name
        if name in m.checker.consts and any(isinstance(d, N.ConstDecl) and d.name == name for d in m.program.decls):
            return m.name, name
        return None, None

    def fn_value(self, e, sig):
        """A top-level function used as a value -> immortal closure with a trampoline."""
        ft = self.ty(e)
        targs = [zonk(e.inst[tp], self.env) for tp in sig.tparams]
        module = self.p.modules_by_name[sig.module]
        target = self.p.instance(module, sig.decl, targs)
        key = ("fnval", target)
        if key not in self.p.static_objs:
            tramp = Fn(target + "__tramp", 1 + len(ft.params))
            self.p.fns.append(tramp)
            for i in sorted(self.p.owned_of(sig.decl)):
                k = rck(ft.params[i])
                if k:
                    tramp.emit("retain", k, 1 + i)      # closure callers lend their arguments
            d = tramp.reg()
            tramp.emit("call", d, target, list(range(1, 1 + len(ft.params))))
            tramp.emit("ret", d)
            sym = f"fnv{len(self.p.static_objs)}"
            self.p.words(sym, [-1, (self.p.closure_td([]), 0), (tramp.name, 0)])
            self.p.static_objs[key] = sym
        return V(self.addr(self.p.static_objs[key]), ft, False)

    def x_Unary(self, e):
        v = self.expr(e.operand)
        t = v.t
        d = self.reg()
        if e.op == "not":
            one = self.const(1)
            self.emit("bin", "xor", d, v.reg, one)
            return V(d, BOOL_T, False)
        if t.name == "Int":
            self.emit("ineg", d, v.reg)
            self.drop(v)
            return V(d, INT_T, True)
        if t.name == "Float":
            sign = self.const(-2 ** 63)
            self.emit("bin", "xor", d, v.reg, sign)
            return V(d, FLOAT_T, False)
        zero = self.const(0)
        self.emit("bin", "sub", d, zero, v.reg)
        return V(d, t, False)

    def compare(self, op, lv, rv, span):
        t = lv.t
        h = t.name if isinstance(t, TCon) else None
        d = self.reg()
        cc = {"==": "eq", "!=": "ne", "<": "lt", ">": "gt", "<=": "le", ">=": "ge"}[op]
        if h == "Int":
            self.emit("icmp", cc, d, lv.reg, rv.reg)
        elif h == "Float":
            self.emit("fcmp", cc, d, lv.reg, rv.reg)
        elif h in ("Bool", "Unit", "Word"):
            self.emit("cmp", cc, d, lv.reg, rv.reg)
        elif h == "Str" and op in ("==", "!="):
            r = self.call_rt("Str_eq", [lv.reg, rv.reg])
            if op == "!=":
                self.emit("bin", "xor", d, r, self.const(1))
            else:
                self.emit("mov", d, r)
        elif h == "Str":
            r = self.call_rt("Str_cmp", [lv.reg, rv.reg])
            self.emit("cmp", cc, d, r, self.const(0))
        elif op in ("==", "!="):
            r = self.call_rt("eq_v", [lv.reg, rv.reg, self.addr(self.p.td(t))])
            if op == "!=":
                self.emit("bin", "xor", d, r, self.const(1))
            else:
                self.emit("mov", d, r)
        else:
            raise NativeUnsupported(f"ordering on {show(t)}")
        return d

    def x_Binary(self, e):
        op = e.op
        if op in ("and", "or"):
            res = self.reg()
            lv = self.expr(e.left)
            self.emit("mov", res, lv.reg)
            rhs, end = self.label("sc"), self.label("scend")
            if op == "and":
                self.emit("br", lv.reg, rhs, end)
            else:
                self.emit("br", lv.reg, end, rhs)
            self.place(rhs)
            rv = self.expr(e.right)
            self.emit("mov", res, rv.reg)
            self.jump(end)
            self.place(end)
            return V(res, BOOL_T, False)
        lv = self.expr(e.left)
        rv = self.expr(e.right)
        if op in ("==", "!=", "<", ">", "<=", ">="):
            d = self.compare(op, lv, rv, e.span)
            self.drop(lv)
            self.drop(rv)
            return V(d, BOOL_T, False)
        t = lv.t
        h = t.name
        d = self.reg()
        if h == "Int":
            iop = {"+": "add", "-": "sub", "*": "mul", "/": "div", "%": "mod"}[op]
            self.emit("iop", iop, d, lv.reg, rv.reg, self.p.span_sym(e.span) if op in "/%" else None)
            self.drop(lv)
            self.drop(rv)
            return V(d, INT_T, True)
        if h == "Float":
            if op == "/" and self.is_rt:
                self.emit("fbin", "div", d, lv.reg, rv.reg)
                return V(d, FLOAT_T, False)
            if op in ("/", "%"):
                name = "float_div" if op == "/" else "float_mod"
                r = self.call_rt(name, [lv.reg, rv.reg, self.addr(self.p.span_sym(e.span))])
                return V(r, FLOAT_T, False)
            self.emit("fbin", {"+": "add", "-": "sub", "*": "mul"}[op], d, lv.reg, rv.reg)
            return V(d, FLOAT_T, False)
        if h == "Word":
            self.emit("bin", {"+": "add", "-": "sub", "*": "mul", "/": "sdiv", "%": "srem"}[op], d, lv.reg, rv.reg)
            return V(d, WORD_T, False)
        if h == "Str" and op == "+":
            r = self.call_rt("Str_concat", [lv.reg, rv.reg])
            self.drop(lv)
            self.drop(rv)
            return V(r, STR_T, True)
        raise NativeUnsupported(f"operator {op} on {show(t)}")

    # ---- calls ------------------------------------------------------------------------
    def args_in_param_order(self, param_names, args, consume=False):
        vals = {}
        pos = 0
        order = []
        for a in args:
            v = self.cexpr(a.value) if consume else self.expr(a.value)
            name = a.name if a.name is not None else param_names[pos]
            if a.name is None:
                pos += 1
            vals[name] = v
            order.append(v)
        return [vals[n] for n in param_names if n in vals], order

    def x_Call(self, e):
        c = e.callee
        if isinstance(c, N.Name) and self.lookup(c.name) is None and c.name not in self.captures:
            name = c.name
            sig = getattr(e, "sig", None)
            if self.is_rt and name in SYS_NAMES and (sig is None or sig.decl is None):
                return self.intrinsic(e, name)
            if sig is not None and sig.decl is not None:
                return self.user_call(e, sig, e.args)
            if name in GLOBALS:
                return self.builtin_global(e, name)
            raise NativeUnsupported(f"call of {name}")
        f = self.expr(c)
        args = [self.expr(a.value) for a in e.args]
        res = self.closure_call(f, args, self.ty(e))
        for a in args:
            self.drop(a)
        self.drop(f)
        return res

    def closure_call(self, f, args, ret_t):
        fp = self.reg()
        self.emit("load", fp, f.reg, 16)
        d = self.reg()
        self.emit("callind", d, fp, [f.reg] + [a.reg for a in args])
        return V(d, ret_t, True)

    def user_call(self, e, sig, args, recv=None):
        """recv: the receiver expression of a method-style call (the first argument)."""
        module = self.p.modules_by_name[sig.module]
        targs = [zonk(e.inst[tp], self.env) for tp in sig.tparams]
        target = self.p.instance(module, sig.decl, targs, kind="rt" if module.is_sys else "user")
        owned = EMPTY if module.is_sys else self.p.owned_of(sig.decl)
        names = [n for n, _ in sig.params]
        exprs = []                         # (parameter index, expression) in evaluation order
        if recv is not None:
            exprs.append((0, recv))
            rest = names[1:]
        else:
            rest = names
        pos = 0
        for a in args:
            name = a.name if a.name is not None else rest[pos]
            if a.name is None:
                pos += 1
            exprs.append((names.index(name), a.value))
        vals = {}
        later = []
        for i, x in exprs:
            if i in owned and self.moves(x):
                later.append((i, x))       # moved after the other arguments are evaluated (they may read it)
            else:
                vals[i] = self.expr(x)
        for i, x in later:
            vals[i] = self.cexpr(x)
        regs = []
        keep = []
        for i in range(len(names)):
            v = vals[i]
            if i in owned:
                regs.append(self.own(v))
            else:
                if later and not v.owned and rck(v.t):
                    self.emit("retain", rck(v.t), v.reg)   # a borrowed view must outlive the moved value
                    v = V(v.reg, v.t, True)
                keep.append(v)
                regs.append(v.reg)
        self.site(e.span)
        d = self.call(target, regs)
        for v in keep:
            self.drop(v)
        return V(d, self.ty(e), True)

    def magic_args(self, rt_decl, n_real, e, sig_tparams, inst):
        out = []
        for p in rt_decl.params[n_real:]:
            if p.name == "rtd":
                out.append(self.addr(self.p.td(self.ty(e))))
            elif p.name == "sp":
                out.append(self.addr(self.p.span_sym(e.span)))
            elif p.name.startswith("td_"):
                tp = p.name[3:]
                out.append(self.addr(self.p.td(zonk(inst[tp], self.env))))
            else:
                raise NativeUnsupported(f"runtime parameter {p.name}")
        return out

    def builtin_global(self, e, name):
        if name in ("Some", "Ok", "Err"):
            t = self.ty(e)
            v = self.cexpr(e.args[0].value)
            tagv = {"Some": 1, "Ok": 0, "Err": 1}[name]
            obj = self.call_rt("obj_new", [self.const(32), self.addr(self.p.td(t))])
            self.emit("store", obj, 16, self.const(tagv))
            self.emit("store", obj, 24, self.own(v))
            return V(obj, t, True)
        if name == "dbg":
            v = self.expr(e.args[0].value)
            text = self.src_text(e.span)
            if text.startswith("dbg(") and text.endswith(")"):
                text = text[4:-1]
            self.call_rt("b_dbg", [v.reg, self.addr(self.p.td(v.t)), self.addr(self.p.str_obj(text)),
                                   self.addr(self.p.span_sym(e.span))])
            return v
        decl = parsed(GLOBALS[name][0])
        target, rt_decl = self.p.rt_fn("b_" + name)
        ordered, order = self.args_in_param_order([p.name for p in decl.params], e.args)
        extra = self.magic_args(rt_decl, len(decl.params), e, decl.type_params, getattr(e, "inst", {}))
        self.site(e.span)
        d = self.call(target, [v.reg for v in ordered] + extra)
        for v in order:
            self.drop(v)
        t = self.ty(e)
        return V(d, t, rck(t) is not None)

    def x_MethodCall(self, e):
        res = getattr(e, "resolved", None)
        if res is None:
            raise NativeUnsupported("unresolved method call")
        kind = res[0]
        if kind == "variant":
            return self.variant_ctor(e, res[1], res[2])
        if kind == "ufcs":
            return self.user_call(e, e.sig, e.args, recv=e.obj)
        if kind == "trait":
            # static dispatch: inside an instance every type parameter is a concrete type
            concrete = zonk(e.inst["Self"], self.env)
            entry = self.p.universe.type_methods.get(getattr(concrete, "name", None), {}).get(e.method)
            if entry is None:
                raise NativeUnsupported(f"no impl of `{res[1]}.{e.method}` for {show(concrete)}")
            return self.user_call(e, entry[1], e.args, recv=e.obj)
        if kind == "builtin" and (res[1], res[2]) in REUSE and self.moves(e.obj):
            return self.builtin_method(e, res[1], res[2], None, consume=True, recv_node=e.obj)
        recv = self.expr(e.obj)
        if kind == "builtin" and (res[1], res[2]) in REUSE and recv.owned and path_of(e.obj) is None:
            return self.builtin_method(e, res[1], res[2], recv, consume=True)   # a temporary: update it in place
        if kind == "to_str":
            r = self.call_rt("show_to_str", [recv.reg, self.addr(self.p.td(recv.t))])
            self.drop(recv)
            return V(r, STR_T, True)
        if kind == "field_fn":
            idx = [f for f, _ in self.p.record_fields(recv.t)].index(e.method)
            f = self.reg()
            self.emit("load", f, recv.reg, 16 + 8 * idx)
            args = [self.expr(a.value) for a in e.args]
            ft = dict(self.p.record_fields(recv.t))[e.method]
            out = self.closure_call(V(f, ft, False), args, self.ty(e))
            for a in args:
                self.drop(a)
            self.drop(recv)
            return out
        if kind == "builtin":
            out = self.builtin_method(e, res[1], res[2], recv)
            return out
        raise NativeUnsupported(kind)

    def builtin_method(self, e, owner, m, recv, consume=False, recv_node=None):
        decl = parsed(METHODS[owner][m][0])
        rt_name = f"{owner}_{m}" + ("_owned" if consume else "")
        target, rt_decl = self.p.rt_fn(rt_name)
        ordered, order = self.args_in_param_order([p.name for p in decl.params[1:]], e.args)
        if consume:
            ordered = [V(self.own(v), v.t, True) for v in ordered]
            order = []
        if recv_node is not None:
            recv = self.cexpr(recv_node)    # the receiver's last use: moved after the arguments
        extra = self.magic_args(rt_decl, len(decl.params), e, decl.type_params, getattr(e, "inst", {}))
        self.site(e.span)
        d = self.call(target, [recv.reg] + [v.reg for v in ordered] + extra)
        for v in order:
            self.drop(v)
        if not consume:
            self.drop(recv)
        t = self.ty(e)
        return V(d, t, rck(t) is not None)

    def variant_ctor(self, e, enum, vname):
        t = self.ty(e)
        fields = list(self.p.universe.enums[enum].variants[vname])
        names = [f for f, _ in fields]
        ordered, _ = self.args_in_param_order(names, e.args, consume=True)
        tagv = self.p.variant_index(t, vname)
        obj = self.call_rt("obj_new", [self.const(24 + 8 * len(names)), self.addr(self.p.td(t))])
        self.emit("store", obj, 16, self.const(tagv))
        for i, v in enumerate(ordered):
            self.emit("store", obj, 24 + 8 * i, self.own(v))
        return V(obj, t, True)

    def x_FieldAccess(self, e):
        b = self.bound_read(e)
        if b is not None:
            return b
        obj = e.obj
        if isinstance(obj, N.Name) and self.lookup(obj.name) is None and obj.name not in self.captures \
                and obj.name in self.p.universe.enums:
            t = self.ty(e)
            return V(self.addr(self.p.static_variant(t, self.p.variant_index(t, e.name))), t, False)
        base = self.expr(obj)
        names = [f for f, _ in self.p.record_fields(base.t)]
        idx = names.index(e.name)
        r = self.reg()
        self.emit("load", r, base.reg, 16 + 8 * idx)
        t = self.ty(e)
        if base.owned:
            k = rck(t)
            if k:
                self.emit("retain", k, r)
            self.drop(base)
            return V(r, t, True)
        return V(r, t, False)

    def x_Try(self, e):
        v = self.expr(e.expr)
        t = v.t
        good_tag = 1 if t.name == "Option" else 0
        tagr = self.reg()
        self.emit("load", tagr, v.reg, 16)
        c = self.reg()
        self.emit("cmp", "eq", c, tagr, self.const(good_tag))
        good, bad = self.label("tgood"), self.label("tbad")
        self.emit("br", c, good, bad)
        self.place(bad)
        if getattr(self, "in_test", False):
            shown = self.call_rt("show_to_str", [v.reg, self.addr(self.p.td(t))])
            pre = self.addr(self.p.str_obj(f"`{self.src_text(e.expr.span)}?` produced "))
            msg = self.call_rt("Str_concat", [pre, shown])
            msg = self.call_rt("Str_concat", [msg, self.addr(self.p.str_obj(" inside a test"))])
            self.call_rt("fail_with", [self.addr(self.p.str_obj("R0008")), msg, self.addr(self.p.span_sym(e.span)),
                                       self.const(0), self.addr(self.p.str_obj(""))])
            self.dead = True
        else:
            self.do_return(v)
        self.place(good)
        inner = self.reg()
        self.emit("load", inner, v.reg, 24)
        it = t.args[0]
        if v.owned:
            k = rck(it)
            if k:
                self.emit("retain", k, inner)
            self.drop(v)
            return V(inner, it, True)
        return V(inner, it, False)

    def x_RecordLit(self, e):
        t = self.ty(e)
        names = [f for f, _ in self.p.record_fields(t)]
        vals = {}
        for f in e.fields:
            vals[f.name] = self.cexpr(f.value)
        obj = self.call_rt("obj_new", [self.const(16 + 8 * len(names)), self.addr(self.p.td(t))])
        for i, n in enumerate(names):
            self.emit("store", obj, 16 + 8 * i, self.own(vals[n]))
        return V(obj, t, True)

    def x_WithExpr(self, e):
        bp = path_of(e.base)
        moved = self.moves(e.base)
        if moved or bp is None:
            src = self.cexpr(e.base)
            if src.owned:
                return self.with_in_place(e, src, bp if moved else None)
            base = src
        else:
            base = self.expr(e.base)
        t = base.t
        fields = self.p.record_fields(t)
        upd = {f.name: self.expr(f.value) for f in e.fields}
        obj = self.call_rt("obj_new", [self.const(16 + 8 * len(fields)), self.addr(self.p.td(t))])
        for i, (n, ft) in enumerate(fields):
            if n in upd:
                self.emit("store", obj, 16 + 8 * i, self.own(upd[n]))
            else:
                r = self.reg()
                self.emit("load", r, base.reg, 16 + 8 * i)
                k = rck(ft)
                if k:
                    self.emit("retain", k, r)
                self.emit("store", obj, 16 + 8 * i, r)
        self.drop(base)
        return V(obj, t, True)

    def with_in_place(self, e, src, bp):
        """`base with {...}` on an owned value: reuse the record when it is unique (else a copy), take out the fields
        being replaced when nothing else reads them, then store the new values."""
        t = src.t
        u = self.unique_record(src)
        saved = (self.bound, self.takeable)
        if bp is not None:
            self.bound = dict(self.bound)
            self.bound[bp] = u
            self.takeable = self.takeable | self.with_takes(e, bp)
        upd = [(f.name, self.cexpr(f.value)) for f in e.fields]
        self.bound, self.takeable = saved
        for name, v in upd:
            off = self.field_off(t, name)
            ft = dict(self.p.record_fields(t))[name]
            k = rck(ft)
            new = self.own(v)
            if k:
                old = self.reg()
                self.emit("load", old, u, off)
                self.emit("release", k, old)
            self.emit("store", u, off, new)
        return V(u, t, True)

    # ---- match ----------------------------------------------------------------------------
    def x_Match(self, e):
        subj = self.expr(e.subject)
        t = self.ty(e)
        res = self.reg()
        self.emit("const", res, 0)
        end = self.label("mend")
        for arm in e.arms:
            nxt = self.label("marm")
            self.push_scope()
            self.pattern(arm.pattern, subj.reg, subj.t, nxt)
            if arm.guard is not None:
                g = self.expr(arm.guard)
                ok = self.label("mg")
                self.emit("br", g.reg, ok, nxt)
                self.place(ok)
            if isinstance(arm.body, N.Block):
                self.block_body(arm.body)
                if not self.dead:
                    self.emit("const", res, 0)
            else:
                v = self.expr(arm.body)
                self.emit("mov", res, self.own(v))
            if not self.dead:
                self.pop_scope()
            else:
                self.scopes.pop()
            self.jump(end)
            self.place(nxt)
        self.call_rt("unreachable", [])
        self.dead = True
        self.place(end)
        self.drop(subj)
        return V(res, t, rck(t) is not None)

    def pattern(self, p, reg, t, fail):
        tp = type(p)
        if tp is N.PWild:
            return
        if tp is N.PBind:
            self.declare(p.name, reg, t, False)
            return
        if tp is N.PLit:
            if isinstance(p.value, str):
                c = self.call_rt("Str_eq", [reg, self.addr(self.p.str_obj(p.value))])
            elif isinstance(p.value, bool):
                c = self.reg()
                self.emit("cmp", "eq", c, reg, self.const(1 if p.value else 0))
            elif isinstance(p.value, float):
                c = self.reg()
                bits = struct.unpack("<q", struct.pack("<d", p.value))[0]
                self.emit("fcmp", "eq", c, reg, self.const(bits))
            else:
                c = self.reg()
                self.emit("icmp", "eq", c, reg, self.const(tag_int(p.value)))
            ok = self.label("pl")
            self.emit("br", c, ok, fail)
            self.place(ok)
            return
        if tp is N.PVariant:
            idx = self.p.variant_index(t, p.variant)
            tagr = self.reg()
            self.emit("load", tagr, reg, 16)
            c = self.reg()
            self.emit("cmp", "eq", c, tagr, self.const(idx))
            ok = self.label("pv")
            self.emit("br", c, ok, fail)
            self.place(ok)
            fts = self.p.variant_fields(t, p.variant)
            for i, (sub, ft) in enumerate(zip(p.args, fts)):
                if isinstance(sub, N.PWild):
                    continue
                fr = self.reg()
                self.emit("load", fr, reg, 24 + 8 * i)
                self.pattern(sub, fr, ft, fail)
            return
        raise NativeUnsupported(tp.__name__)

    # ---- lambdas ---------------------------------------------------------------------------
    def x_Lambda(self, e):
        ft = self.ty(e)
        own_names = {p.name for p in e.params}
        for n in N.walk(e.body):
            if isinstance(n, N.Let):
                own_names.add(n.name)
            elif isinstance(n, N.For):
                own_names.add(n.var)
            elif isinstance(n, N.PBind):
                own_names.add(n.name)
        free = []
        for n in N.walk(e.body):
            if isinstance(n, (N.Name, N.Assign)):
                nm = n.name
                if nm in own_names or nm in [f[0] for f in free]:
                    continue
                loc = self.lookup(nm)
                if loc is not None:
                    if isinstance(n, N.Assign):
                        raise NativeUnsupported("lambda assigns a captured variable")
                    free.append((nm, loc))
                elif nm in self.captures:
                    free.append((nm, None))
        for n in N.walk(e.body):
            if isinstance(n, N.Assign) and n.name not in own_names:
                raise NativeUnsupported("lambda assigns a captured variable")
        cap_types = []
        cap_vals = []
        for nm, loc in free:
            if loc is not None and self.bound_prefix(nm) == nm:
                v = V(self.bound[nm], loc.t, False)
            elif loc is not None:
                v = self.read_local(nm, loc)
            else:
                idx, t = self.captures[nm]
                r = self.reg()
                self.emit("load", r, self.closure_self, 24 + 8 * idx)
                v = V(r, t, False)
            cap_types.append(v.t)
            cap_vals.append(v)
        name = self.p.uid(self.fn.name + "__lam")
        lam = FnLowering(self.p, self.m, self.env, self.is_rt)
        lam.lambda_fn(name, e, ft, [(nm, t) for (nm, _), t in zip(free, cap_types)])
        td = self.p.closure_td(cap_types)
        obj = self.call_rt("obj_new", [self.const(24 + 8 * len(cap_vals)), self.addr(td)])
        fp = self.addr(name)
        self.emit("store", obj, 16, fp)
        for i, v in enumerate(cap_vals):
            self.emit("store", obj, 24 + 8 * i, self.own(v))
        return V(obj, ft, True)

    def lambda_fn(self, name, e, ft, captured):
        self.fn = Fn(name, 1 + len(e.params), "<lambda>")
        self.p.fns.append(self.fn)
        self.closure_self = 0
        self.captures = {nm: (i, t) for i, (nm, t) in enumerate(captured)}
        self.ret_t = ft.ret
        self.ensures = None
        self.decl = None
        self.push_scope()
        for i, p in enumerate(e.params):
            self.declare(p.name, 1 + i, ft.params[i], False)
        if not self.is_rt:
            live = Liveness(self.locals_of([p.name for p in e.params], e.body))
            self.cand = live.run_block(e.body) if isinstance(e.body, N.Block) else live.run_expr(e.body)
            self.emit("enter", self.p.str_obj("<lambda>"))
        if isinstance(e.body, N.Block):
            self.block_body(e.body)
            if not self.dead:
                self.do_return(V(self.const(0), UNIT_T, True))
        else:
            v = self.expr(e.body)
            self.do_return(v)

    # ---- system intrinsics (runtime modules only) ---------------------------------------------
    def intrinsic(self, e, name):
        args = [self.expr(a.value) for a in e.args]
        regs = [a.reg for a in args]
        d = self.reg()
        simple = {"w_and": "and", "w_or": "or", "w_xor": "xor", "w_shl": "shl", "w_shr": "shr", "w_sar": "sar",
                  "w_udiv": "udiv", "w_urem": "urem", "w_mulhi": "umulhi"}
        if name == "peek":
            self.emit("load", d, regs[0], 0)
            return V(d, WORD_T, False)
        if name == "poke":
            self.emit("store", regs[0], 0, regs[1])
            return V(d, UNIT_T, False)
        if name in ("peek8", "peek32"):
            self.emit("load8" if name == "peek8" else "load32", d, regs[0], 0)
            return V(d, WORD_T, False)
        if name in ("poke8", "poke32"):
            self.emit("store8" if name == "poke8" else "store32", regs[0], 0, regs[1])
            return V(d, UNIT_T, False)
        if name in simple:
            self.emit("bin", simple[name], d, regs[0], regs[1])
            return V(d, WORD_T, False)
        if name == "w_ult":
            self.emit("cmp", "ult", d, regs[0], regs[1])
            return V(d, BOOL_T, False)
        if name in ("bits", "fbits", "f2w_bits"):
            self.emit("mov", d, regs[0])
            return V(d, WORD_T, False)
        if name in ("unbits", "ffrom"):
            self.emit("mov", d, regs[0])
            return V(d, self.ty(e), False)
        if name == "tag":
            two = self.const(1)
            self.emit("bin", "shl", d, regs[0], two)
            self.emit("bin", "or", d, d, two)
            return V(d, INT_T, False)
        if name == "untag":
            one = self.const(1)
            self.emit("bin", "sar", d, regs[0], one)
            return V(d, WORD_T, False)
        if name == "is_small":
            one = self.const(1)
            self.emit("bin", "and", d, regs[0], one)
            return V(d, BOOL_T, False)
        if name == "w2f":
            self.emit("i2f", d, regs[0])
            return V(d, FLOAT_T, False)
        if name == "f2w":
            self.emit("f2i", d, regs[0])
            return V(d, WORD_T, False)
        if name in ("fsqrt", "fsin", "fcos", "fln", "fexp"):
            self.emit("fun", name[1:], d, regs[0])
            return V(d, FLOAT_T, False)
        if name == "fpow":
            self.emit("fpow", d, regs[0], regs[1])
            return V(d, FLOAT_T, False)
        if name == "static_addr":
            lit = e.args[0].value
            if not isinstance(lit, N.StrLit) or not all(isinstance(x, str) for x in lit.parts):
                raise NativeUnsupported("static_addr needs a literal")
            self.emit("addr", d, "".join(lit.parts))
            return V(d, WORD_T, False)
        if name in ("call1", "call2"):
            fp = self.reg()
            self.emit("load", fp, regs[0], 16)
            self.emit("callind", d, fp, regs)
            return V(d, WORD_T, False)
        if name == "frame_ptr":
            self.emit("fp", d)
            return V(d, WORD_T, False)
        if name == "user_main":
            self.emit("call", d, "__user_main", [])
            return V(d, WORD_T, False)
        if name == "init_consts":
            self.emit("call", d, "__init_consts", [])
            return V(d, UNIT_T, False)
        if name in ("retain_t", "release_t"):
            k = rck(args[0].t)
            if k:
                self.emit("retain" if name == "retain_t" else "release", k, regs[0])
            return V(d, UNIT_T, False)
        if name.startswith("os_"):
            self.emit("call", d, name, regs)
            t = self.ty(e)
            return V(d, t, False)
        raise NativeUnsupported(f"intrinsic {name}")


def lower_test(prog, module, t, index):
    fl = FnLowering(prog, module, {}, False)
    fl.in_test = True
    name = f"__test{index}"
    fl.fn = Fn(name, 0, f'test "{t.name}"')
    prog.fns.append(fl.fn)
    fl.ret_t = UNIT_T
    fl.ensures = None
    fl.decl = None
    fl.push_scope()
    fl.cand = Liveness(fl.locals_of([], t.body)).run_block(t.body)
    fl.emit("enter", prog.str_obj(f'test "{t.name}"'))
    fl.block_body(t.body)
    if not fl.dead:
        fl.do_return(V(fl.const(0), UNIT_T, True))
    return name


def lower_program(loaded, image, tests=None):
    """Lower the whole program; returns (Program, runtime-helper map for the emitter).

    tests: None -> run main(); a list of TestDecl -> the executable runs test #argv[1].
    """
    prog = Program(loaded, image)
    main_mod = loaded.main
    um = Fn("__user_main", 0)
    prog.fns.append(um)
    r = um.reg()
    if tests is None:
        main_decl = next(d for d in main_mod.program.decls if isinstance(d, N.FnDecl) and d.name == "main")
        main_name = prog.instance(main_mod, main_decl, [])
        um.emit("call", r, main_name, [])
        um.emit("ret", r)
    else:
        main_decl = tests[0] if tests else main_mod.program
        names = [lower_test(prog, main_mod, t, i) for i, t in enumerate(tests)]
        sel = um.reg()
        um.emit("call", sel, "test_index_arg", [])
        for i, nm in enumerate(names):
            c, k, yes, no = um.reg(), um.reg(), um.label("t"), um.label("n")
            um.emit("const", k, i)
            um.emit("cmp", "eq", c, sel, k)
            um.emit("br", c, yes, no)
            um.emit("label", yes)
            um.emit("call", r, nm, [])
            um.emit("ret", r)
            um.emit("label", no)
        um.emit("const", r, 0)
        um.emit("ret", r)
    # constants initialiser: the runtime's own constants first (heap layout offsets, kinds — plain literals),
    # then the program's modules in dependency order (their values may allocate, which needs the runtime's)
    ic = Fn("__init_consts", 0)
    prog.fns.append(ic)
    for m in list(getattr(loaded, "runtime", [])) + list(loaded.modules):
        for d in m.program.decls:
            if isinstance(d, N.ConstDecl):
                fl = FnLowering(prog, m, {}, m.is_sys)
                fl.fn = ic
                fl.push_scope()
                v = fl.expr(d.value)
                slot = fl.addr(prog.const_slot(m.name, d.name))
                ic.emit("store", slot, 0, fl.own(v))
    z = ic.reg()
    ic.emit("const", z, 0)
    ic.emit("ret", z)
    rt = {}
    for helper in ("free", "int_add", "int_sub", "int_mul", "int_div", "int_mod", "int_neg", "int_cmp",
                   "div_zero", "stack_overflow", "main_entry"):
        rt[helper], _ = prog.rt_fn(helper)
    prog.run()
    # static descriptors the runtime refers to by name
    for nm, t in (("td_Str", STR_T), ("td_Int", INT_T), ("td_Float", FLOAT_T), ("td_Bool", BOOL_T),
                  ("td_Unit", UNIT_T), ("td_Bytes", TCon("Bytes"))):
        sym = prog.td(t)
        image.data_syms[nm] = image.data_syms[sym]
    prog.words("td_Big", [K_BIG, (prog.str_obj("Int"), 0), 0, 0, 0, 0])
    prog.words("obj_None", [-1, (prog.td(TCon("Option", [UNIT_T])), 0), 0])
    prog.words("td_Buf", [K_BUF, (prog.str_obj("Buf"), 0), 0, 0, 0, 0])
    prog.words("td_ListStr", [K_LIST, (prog.str_obj("List"), 0), ("td_Str", 0), 0, 0, 0])
    if tests is None:
        main_ret = zonk(prog.loaded.main.checker.fns["main"].ret, {})
        prog.words("main_kind", [1 if main_ret.name == "Result" else 0])
        main_span = main_decl.name_span
    else:
        prog.words("main_kind", [0])
        main_span = tests[0].span if tests else prog.loaded.main.program.span
    image.data_syms["main_span"] = image.data_syms[prog.span_sym(main_span)]
    image.add_bss("g_rt", 8 * 4096)
    image.add_bss("g_outbuf", 65536)
    image.add_bss("g_inbuf", 65536)
    return prog, rt
