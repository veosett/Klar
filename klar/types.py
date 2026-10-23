"""Type representation and unification (with undo trail)."""


class Type:
    pass


class TCon(Type):
    __slots__ = ("name", "args")

    def __init__(self, name, args=()):
        self.name = name
        self.args = tuple(args)

    def __repr__(self):
        return show(self)


class Eff:
    """The effects of a function type. Fixed: exactly `names` (from a written type: `fn() -> Unit uses io`).
    Flexible: at least `names`, decided by unification (a lambda: the effects its body uses; a named function: its
    `uses`) — a function with fewer effects fits where more are allowed. Polymorphic (`poly`): a function parameter
    of a built-in (`map`, `filter`, ...); every call gets a fresh flexible one and needs the effects it ends with."""
    __slots__ = ("names", "fixed", "poly", "ref")

    def __init__(self, names=(), fixed=True, poly=False):
        self.names = frozenset(names)
        self.fixed = fixed
        self.poly = poly
        self.ref = None


PURE = Eff()


def flex(names=()):
    return Eff(names, fixed=False)


def eprune(e):
    while e.ref is not None:
        e = e.ref
    return e


def eff_names(t):
    """The effects of calling a value of function type t (empty for anything else)."""
    t = prune(t)
    return eprune(t.eff).names if isinstance(t, TFn) else frozenset()


def _unify_eff(a, b, trail):
    a, b = eprune(a), eprune(b)
    if a is b:
        return True
    if a.fixed and b.fixed:
        return a.names == b.names
    if a.fixed:
        a, b = b, a
    # a is flexible: it may grow up to b (a fixed b), or the smaller of two flexible ones takes the larger
    if a.names <= b.names:
        a.ref = b
        trail.append(a)
        return True
    if not b.fixed and b.names <= a.names:
        b.ref = a
        trail.append(b)
        return True
    return False


class TFn(Type):
    __slots__ = ("params", "ret", "eff")

    def __init__(self, params, ret, eff=None):
        self.params = list(params)
        self.ret = ret
        self.eff = PURE if eff is None else eff

    def __repr__(self):
        return show(self)


class TVar(Type):
    _n = 0

    def __init__(self, hint=None):
        TVar._n += 1
        self.id = TVar._n
        self.ref = None
        self.hint = hint

    def __repr__(self):
        return show(self)


class TParam(Type):
    """A rigid generic parameter inside the body of a generic function."""
    __slots__ = ("name",)

    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return self.name


class _Special(Type):
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return self.name


ANY = _Special("?")       # error recovery: unifies with everything
NEVER = _Special("Never")  # type of `fail(...)`, `return`-only blocks

INT = TCon("Int")
FLOAT = TCon("Float")
BOOL = TCon("Bool")
STR = TCon("Str")
UNIT = TCon("Unit")


def list_of(t):
    return TCon("List", [t])


def option_of(t):
    return TCon("Option", [t])


def result_of(t, e):
    return TCon("Result", [t, e])


def map_of(k, v):
    return TCon("Map", [k, v])


def prune(t):
    while isinstance(t, TVar) and t.ref is not None:
        t = t.ref
    return t


def occurs(v, t):
    t = prune(t)
    if t is v:
        return True
    if isinstance(t, TCon):
        return any(occurs(v, a) for a in t.args)
    if isinstance(t, TFn):
        return any(occurs(v, p) for p in t.params) or occurs(v, t.ret)
    return False


def _unify(a, b, trail):
    a = prune(a)
    b = prune(b)
    if a is b:
        return True
    if a is ANY or b is ANY or a is NEVER or b is NEVER:
        return True
    if isinstance(a, TVar):
        if occurs(a, b):
            return False
        a.ref = b
        trail.append(a)
        return True
    if isinstance(b, TVar):
        return _unify(b, a, trail)
    if isinstance(a, TCon) and isinstance(b, TCon):
        if a.name != b.name or len(a.args) != len(b.args):
            return False
        return all(_unify(x, y, trail) for x, y in zip(a.args, b.args))
    if isinstance(a, TFn) and isinstance(b, TFn):
        if len(a.params) != len(b.params):
            return False
        return (all(_unify(x, y, trail) for x, y in zip(a.params, b.params)) and _unify(a.ret, b.ret, trail)
                and _unify_eff(a.eff, b.eff, trail))
    if isinstance(a, TParam) and isinstance(b, TParam):
        return a.name == b.name
    return False


def unify(a, b):
    """Unify a and b; on failure, undo any partial bindings."""
    trail = []
    if _unify(a, b, trail):
        return True
    for v in trail:
        v.ref = None
    return False


def subst(t, mapping):
    t = prune(t)
    if isinstance(t, TParam):
        return mapping.get(t.name, t)
    if isinstance(t, TCon):
        if not t.args:
            return t
        return TCon(t.name, [subst(a, mapping) for a in t.args])
    if isinstance(t, TFn):
        e = eprune(t.eff)
        return TFn([subst(p, mapping) for p in t.params], subst(t.ret, mapping), flex() if e.poly else t.eff)
    return t


def show(t):
    t = prune(t)
    if isinstance(t, TCon):
        if t.args:
            return f"{t.name}[{', '.join(show(a) for a in t.args)}]"
        return t.name
    if isinstance(t, TFn):
        names = eprune(t.eff).names
        ret = show(t.ret)
        if not names:
            return f"fn({', '.join(show(p) for p in t.params)}) -> {ret}"
        if isinstance(prune(t.ret), TFn):
            ret = f"({ret})"
        return f"fn({', '.join(show(p) for p in t.params)}) -> {ret} uses {', '.join(sorted(names))}"
    if isinstance(t, TVar):
        return "_"
    if isinstance(t, TParam):
        return t.name
    return t.name


def head(t):
    t = prune(t)
    return t.name if isinstance(t, TCon) else None


def is_unit(t):
    return head(t) == "Unit"
