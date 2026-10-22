"""Ownership for the native backend: "functional but in place".

Values are immutable, so an update like `w with { spans: w.spans.set(k, v) }` must copy — unless nobody else can
see the old value. Two analyses find where the copy can be skipped (compiler/own.klar is the same in Klar):

* `infer_owned`: which parameters a function *consumes* (moves into a result: the base of `with`, the receiver of
  `push`/`set`/..., a `let`/`return` value, a field of a new record, an argument for a consumed parameter of
  another function — a fixpoint over the call graph). Those parameters are passed owned: the caller gives up its
  reference (or retains one for the callee) and the callee releases them. Every other parameter stays borrowed.
* `Liveness`: which uses of a local variable are its last, path by path (`w`, `w.img`, `a.w`). A consuming use
  that is the last one *moves* the value (no retain; the variable gets an immortal placeholder), so a record or
  collection that was unique stays unique and the runtime updates it in place.

A candidate use must also be the only use of its path in its statement (other uses would be borrowed views that
the move could invalidate), except for the other arguments of the same call (they are retained around the call)
and for the field values of a `with` whose base it is (they read the reused record).
"""
from .. import nodes as N

# methods whose receiver may be updated in place (runtime function <Owner>_<m>_owned)
REUSE = {("List", "push"), ("List", "set"), ("List", "insert"), ("List", "remove_at"), ("List", "concat"),
         ("Bytes", "push"), ("Bytes", "push_le"), ("Bytes", "set"), ("Bytes", "concat"),
         ("Map", "set"), ("Map", "remove"), ("Map", "update")}

EMPTY = frozenset()


def path_of(e):
    """`x`, `x.f.g` for a Name or a chain of field accesses on a Name; else None."""
    names = []
    while isinstance(e, N.FieldAccess):
        names.append(e.name)
        e = e.obj
    if isinstance(e, N.Name):
        return ".".join([e.name] + names[::-1])
    return None


def root_of(path):
    return path.split(".", 1)[0]


def extends(p, q):
    """p is q or lies inside q."""
    return p == q or p.startswith(q + ".")


def overlaps(p, q):
    return extends(p, q) or extends(q, p)


def hits(p, item):
    """Does a move of path p break the later use `item` = (path, fields the use does not read)?"""
    q, excl = item
    if extends(q, p):
        return True
    if p.startswith(q + "."):
        return p[len(q) + 1:].split(".", 1)[0] not in excl
    return False


def without_root(live, name):
    return frozenset(it for it in live if root_of(it[0]) != name)


def builtin_kind(e):
    res = getattr(e, "resolved", None)
    return res[0] if res else None


def user_callee(e):
    """(decl, parameter names, receiver node or None) for a direct call of a user function, else None."""
    if isinstance(e, N.Call) and isinstance(e.callee, N.Name):
        sig = getattr(e, "sig", None)
        if sig is not None and getattr(sig, "decl", None) is not None:
            return sig.decl, [n for n, _ in sig.params], None
        return None
    if isinstance(e, N.MethodCall) and builtin_kind(e) == "ufcs":
        sig = getattr(e, "sig", None)
        if sig is not None and getattr(sig, "decl", None) is not None:
            return sig.decl, [n for n, _ in sig.params], e.obj
    return None


def arg_positions(names, args):
    """(parameter index, argument) in source order, like the lowering's args_in_param_order."""
    out = []
    pos = 0
    for a in args:
        name = a.name if a.name is not None else names[pos]
        if a.name is None:
            pos += 1
        out.append((names.index(name), a))
    return out


def names_in(nodes):
    return {n.name for n in N.walk(nodes) if isinstance(n, N.Name)}


# ---- parameters ---------------------------------------------------------------------------------------------------
def infer_owned(decls):
    """{id(FnDecl): frozenset of consumed parameter indices} for the given (user) function declarations."""
    owned = {}
    edges = []
    for d in decls:
        pidx = {p.name: i for i, p in enumerate(d.params)}
        keep = names_in(d.ensures)       # postconditions read the parameters after the body
        got = set()

        def param(e):
            p = path_of(e)
            if p is None:
                return None
            r = root_of(p)
            return pidx[r] if r in pidx and r not in keep else None

        def mark(e):
            i = param(e)
            if i is not None:
                got.add(i)

        for n in N.walk(d.body):
            if isinstance(n, (N.Let, N.Assign, N.Return)):
                if n.value is not None:
                    mark(n.value)
            elif isinstance(n, N.RecordLit):
                for f in n.fields:
                    mark(f.value)
            elif isinstance(n, N.WithExpr):
                mark(n.base)
                for f in n.fields:
                    mark(f.value)
            elif isinstance(n, N.ListLit):
                for it in n.items:
                    mark(it)
            elif isinstance(n, N.MapLit):
                for en in n.entries:
                    mark(en.key)
                    mark(en.value)
            elif isinstance(n, (N.Call, N.MethodCall)):
                uc = user_callee(n)
                if uc is not None:
                    callee, pnames, recv = uc
                    if recv is not None:
                        i = param(recv)
                        if i is not None:
                            edges.append((id(d), i, id(callee), 0))
                        pos = [(j + 1, a) for j, a in arg_positions(pnames[1:], n.args)]
                    else:
                        pos = arg_positions(pnames, n.args)
                    for j, a in pos:
                        i = param(a.value)
                        if i is not None:
                            edges.append((id(d), i, id(callee), j))
                elif isinstance(n, N.Call) and isinstance(n.callee, N.Name) and n.callee.name in ("Some", "Ok", "Err"):
                    for a in n.args:
                        mark(a.value)
                elif isinstance(n, N.MethodCall):
                    k = builtin_kind(n)
                    if k == "variant":
                        for a in n.args:
                            mark(a.value)
                    elif k == "builtin" and (n.resolved[1], n.resolved[2]) in REUSE:
                        mark(n.obj)
        owned[id(d)] = got
    changed = True
    while changed:
        changed = False
        for d, i, c, j in edges:
            if j in owned.get(c, ()) and i not in owned[d]:
                owned[d].add(i)
                changed = True
    return {k: frozenset(v) for k, v in owned.items()}


# ---- last uses ----------------------------------------------------------------------------------------------------
class Occ:
    __slots__ = ("node", "path", "stmt", "seq", "regions", "parent", "live", "alias", "anc")


def finished(o2, o):
    """Is o2 inside a subexpression that has produced a value of its own before o runs? (Then no borrowed view of
    o2 is still held.) Subexpressions are evaluated one after the other, so it is enough that an expression that
    computes a new value (a call, an operator, a literal...) lies between o2 and the closest common ancestor."""
    k = 0
    while k < len(o.anc) and k < len(o2.anc) and o.anc[k][0] == o2.anc[k][0]:
        k += 1
    return any(c for _, c in o2.anc[k:])


class Liveness:
    """Backward liveness over a function body; `candidates` are the uses that may move their value."""

    def __init__(self, locals_, no_move=()):
        self.locals = set(locals_)
        self.no_move = set(no_move)
        self.alias = {}           # pattern binding -> the path of the matched value (it borrows from it)
        self.occs = {}            # id(node) -> Occ (the last pass over a loop wins)
        self.regions = []
        self.stmt = None
        self.seq = 0
        self.loops = []           # [exit live set, head live set]
        self.anc = []             # (id, computes a new value) of the expressions around the current one

    # ---- driver
    def run_block(self, block):
        self.block(block, EMPTY)
        return self.candidates()

    def run_expr(self, e):
        self.stmt = ("expr", id(e))
        self.ex(e, EMPTY)
        return self.candidates()

    def candidates(self):
        by_stmt = {}
        for o in self.occs.values():
            by_stmt.setdefault(o.stmt, []).append(o)
        out = set()
        for occs in by_stmt.values():
            for o in occs:
                if o.alias or root_of(o.path) in self.no_move:
                    continue
                if any(hits(o.path, it) for it in o.live):
                    continue
                ok = True
                for o2 in occs:
                    if o2 is o or not overlaps(o2.path, o.path) or finished(o2, o):
                        continue
                    r = o.parent
                    if r is None or r not in o2.regions:
                        ok = False
                    elif r[0] == "c" and not o2.path.startswith(o.path + "."):
                        ok = False
                    elif r[0] == "w" and not extends(o2.path, o.path):
                        ok = False
                    if not ok:
                        break
                if ok:
                    out.add(id(o.node))
        return out

    # ---- statements
    def block(self, b, live):
        for s in reversed(b.stmts):
            live = self.stmt_(s, live)
        return live

    def stmt_(self, s, live):
        outer = (self.stmt, self.anc, self.regions)
        self.stmt, self.anc, self.regions = ("stmt", id(s)), [], []
        try:
            return self._stmt(s, live)
        finally:
            self.stmt, self.anc, self.regions = outer

    def _stmt(self, s, live):
        t = type(s)
        if t is N.Let:
            return self.ex(s.value, without_root(live, s.name))
        if t is N.Assign:
            return self.ex(s.value, without_root(live, s.name))
        if t is N.Return:
            return self.ex(s.value, EMPTY) if s.value is not None else EMPTY
        if t is N.ExprStmt:
            return self.ex(s.expr, live)
        if t is N.If:
            lt = self.block(s.then, live)
            if isinstance(s.else_, N.If):
                le = self.stmt_(s.else_, live)
            elif s.else_ is not None:
                le = self.block(s.else_, live)
            else:
                le = live
            return self.ex(s.cond, lt | le)
        if t is N.While:
            head = live
            while True:
                self.loops.append([live, head])
                body_in = self.block(s.body, head)
                self.loops.pop()
                new = self.ex(s.cond, body_in | live) | head
                if new == head:
                    return head
                head = new
        if t is N.For:
            head = without_root(live, s.var)
            while True:
                self.loops.append([live, head])
                body_in = self.block(s.body, head)
                self.loops.pop()
                new = without_root(body_in, s.var) | head
                if new == head:
                    break
                head = new
            return self.ex(s.iter, head)
        if t is N.Break:
            return self.loops[-1][0]
        if t is N.Continue:
            return self.loops[-1][1]
        if t is N.Assert:
            if s.message is not None:
                live = self.ex(s.message, live)
            return self.ex(s.cond, live)
        raise ValueError(t.__name__)

    # ---- expressions (walked backwards, in reverse evaluation order)
    def local_path(self, e):
        p = path_of(e)
        if p is None:
            return None, False
        r = root_of(p)
        if r in self.alias:
            a = self.alias[r]
            return (a, True) if a is not None else (None, False)
        return (p, False) if r in self.locals else (None, False)

    def occ(self, e, path, alias, parent, live, check, excl=EMPTY):
        """Records a use; `check` is what must not overlap it for a move (the live set after its call / `with`)."""
        o = Occ()
        o.node, o.path, o.stmt, o.alias, o.parent = e, path, self.stmt, alias, parent
        self.seq += 1
        o.seq = self.seq
        o.regions = tuple(self.regions)
        o.anc = tuple(self.anc)
        o.live = check
        self.occs[id(e)] = o
        return live | {(path, excl)}

    def ex(self, e, live, parent=None, check=None, excl=EMPTY):
        if e is None:
            return live
        path, alias = self.local_path(e)
        if path is not None:
            return self.occ(e, path, alias, parent if not alias else None, live, live if check is None else check,
                            excl if not alias else EMPTY)
        t = type(e)
        passes = t in (N.FieldAccess, N.Try) or (t is N.Call and isinstance(e.callee, N.Name) and
                                                 e.callee.name == "dbg" and user_callee(e) is None)
        self.anc.append((id(e), not passes))
        try:
            return self._ex(e, t, live)
        finally:
            self.anc.pop()

    def _ex(self, e, t, live):
        if t in (N.IntLit, N.FloatLit, N.BoolLit, N.UnitLit, N.Name):
            return live
        if t is N.FieldAccess:
            return self.ex(e.obj, live)
        if t is N.StrLit:
            for p in reversed(e.parts):
                if not isinstance(p, str):
                    live = self.ex(p, live)
            return live
        if t is N.ListLit:
            for it in reversed(e.items):
                live = self.ex(it, live)
            return live
        if t is N.MapLit:
            for en in reversed(e.entries):
                live = self.ex(en.value, live)
                live = self.ex(en.key, live)
            return live
        if t is N.Unary:
            return self.ex(e.operand, live)
        if t is N.Binary:
            return self.ex(e.left, self.ex(e.right, live))
        if t is N.Try:
            return self.ex(e.expr, live)
        if t is N.RecordLit:
            for f in reversed(e.fields):
                live = self.ex(f.value, live)
            return live
        if t is N.WithExpr:
            after = live
            key = ("w", id(e))
            self.regions.append(key)
            for f in reversed(e.fields):
                live = self.ex(f.value, live)
            self.regions.pop()
            return self.ex(e.base, live, parent=key, check=after, excl=frozenset(f.name for f in e.fields))
        if t is N.Call:
            after = live
            key = ("c", id(e))
            direct = user_callee(e) is not None
            self.regions.append(key)
            for a in reversed(e.args):
                live = self.ex(a.value, live, parent=key if direct else None, check=after if direct else None)
            self.regions.pop()
            if not isinstance(e.callee, N.Name) or self.local_path(e.callee)[0] is not None:
                live = self.ex(e.callee, live)
            return live
        if t is N.MethodCall:
            k = builtin_kind(e)
            after = live
            key = ("c", id(e))
            reuse = k == "builtin" and (e.resolved[1], e.resolved[2]) in REUSE
            direct = k in ("ufcs", "trait")
            self.regions.append(key)
            for a in reversed(e.args):
                live = self.ex(a.value, live, parent=key if direct else None, check=after if direct else None)
            self.regions.pop()
            if k == "variant":
                return live
            if direct or reuse:
                return self.ex(e.obj, live, parent=key, check=after)
            return self.ex(e.obj, live)
        if t is N.Match:
            sp, _ = self.local_path(e.subject)
            for arm in e.arms:
                for n in N.walk(arm.pattern):
                    if isinstance(n, N.PBind):
                        self.alias[n.name] = sp
            outs = EMPTY
            for arm in e.arms:
                if isinstance(arm.body, N.Block):
                    lv = self.block(arm.body, live)
                else:
                    lv = self.ex(arm.body, live)
                if arm.guard is not None:
                    lv = self.ex(arm.guard, lv)
                outs = outs | lv
            return self.ex(e.subject, outs)
        if t is N.Lambda:
            own = {p.name for p in e.params}
            for n in N.walk(e.body):
                if isinstance(n, N.Let):
                    own.add(n.name)
                elif isinstance(n, N.For):
                    own.add(n.var)
                elif isinstance(n, N.PBind):
                    own.add(n.name)
            seen = []
            for n in N.walk(e.body):
                if isinstance(n, N.Name) and n.name not in own and n.name not in seen:
                    seen.append(n.name)
            for nm in seen:
                if nm in self.alias and self.alias[nm] is not None:
                    live = live | {(self.alias[nm], EMPTY)}
                elif nm in self.locals:
                    live = live | {(nm, EMPTY)}
            return live
        raise ValueError(t.__name__)
