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


class TFn(Type):
    __slots__ = ("params", "ret")

    def __init__(self, params, ret):
        self.params = list(params)
        self.ret = ret

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
        return all(_unify(x, y, trail) for x, y in zip(a.params, b.params)) and _unify(a.ret, b.ret, trail)
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
        return TFn([subst(p, mapping) for p in t.params], subst(t.ret, mapping))
    return t


def show(t):
    t = prune(t)
    if isinstance(t, TCon):
        if t.args:
            return f"{t.name}[{', '.join(show(a) for a in t.args)}]"
        return t.name
    if isinstance(t, TFn):
        return f"fn({', '.join(show(p) for p in t.params)}) -> {show(t.ret)}"
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
