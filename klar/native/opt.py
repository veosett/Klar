"""KIR optimizer: runs on every function before machine-code emission.

Passes (all local and conservative — correctness first):
  1. block-local forward folding: constants into immediates (`bini`, `cmpi`, `iopi`, `icmpi`),
     `x + c` into load/store displacements, copy propagation, no-op retain/release of
     values known to be small Ints;
  2. compare-and-branch fusion (`brc`, `brci`, `ibr`, `ibri`, `fbr`): the Bool is never
     materialized; releases between the compare and the branch are delayed into both
     successors (delaying a release is always safe);
  3. dead-code elimination of pure instructions whose result is unused.

New instruction forms introduced here (understood by emit.py):
  ("bini", op, d, x, imm)          ("cmpi", cc, d, x, imm)
  ("bink", op, d, x, c)            udiv/urem/sdiv/srem by a positive constant (multiply by reciprocal)
  ("iopi", op, d, x, timm, span)   tagged-Int op with a constant small operand (timm is tagged)
  ("icmpi", cc, d, x, timm)
  ("brc", cc, x, y, Lt, Lf)  ("brci", cc, x, imm, Lt, Lf)  ("ibr", cc, x, y, Lt, Lf)
  ("brti", "ne", x, imm8, Lt, Lf)  (branch on x & imm8 != 0)
  ("ibri", cc, x, timm, Lt, Lf)  ("fbr", cc, x, y, Lt, Lf)
"""

I32 = (-2 ** 31, 2 ** 31)

PURE = {"const", "fp", "mov", "addr", "bin", "bini", "bink", "cmp", "cmpi", "fbin", "fcmp", "i2f", "f2i", "fun", "fpow",
        "load", "load8", "load32"}
# instructions that never call out of line (so caller-saved registers survive them)
NO_CALL = {"const", "fp", "mov", "addr", "bin", "bini", "bink", "cmp", "cmpi", "fbin", "fcmp", "i2f", "f2i", "fun", "fpow",
           "load", "load8", "load32", "store", "store8", "store32", "retain", "label", "jmp", "br", "brc",
           "brci", "brti", "fbr", "ret", "leave", "site"}
TERMINATORS = {"jmp", "br", "ret", "brc", "brci", "brti", "ibr", "ibri", "fbr"}
SWAP = {"eq": "eq", "ne": "ne", "lt": "gt", "gt": "lt", "le": "ge", "ge": "le",
        "ult": "ugt", "ugt": "ult", "ule": "uge", "uge": "ule"}
COMMUTATIVE = {"add", "and", "or", "xor", "mul"}
BINI_OPS = {"add", "sub", "and", "or", "xor", "shl", "shr", "sar", "mul"}


def fits(v):
    return I32[0] <= v < I32[1]


def wrap(v):
    v &= (1 << 64) - 1
    return v - (1 << 64) if v >= 1 << 63 else v


# ---- operand tables -------------------------------------------------------------------------
def defs(ins):
    op = ins[0]
    if op in ("const", "fp", "mov", "addr", "i2f", "f2i", "ineg", "fpow", "load", "load8", "load32"):
        return (ins[1],)
    if op in ("bin", "bini", "bink", "cmp", "cmpi", "fbin", "fcmp", "fun", "iop", "iopi", "icmp", "icmpi"):
        return (ins[2],)
    if op == "call":
        return (ins[1],) if ins[1] is not None else ()
    if op == "callind":
        return (ins[1],) if ins[1] is not None else ()
    return ()


def uses(ins):
    op = ins[0]
    if op in ("mov", "i2f", "f2i", "ineg"):
        return (ins[2],)
    if op in ("bin", "cmp", "fbin", "fcmp", "iop", "icmp"):
        return (ins[3], ins[4])
    if op in ("bini", "bink", "cmpi", "fun", "iopi", "icmpi"):
        return (ins[3],)
    if op == "fpow":
        return (ins[2], ins[3])
    if op in ("load", "load8", "load32"):
        return (ins[2],)
    if op in ("store", "store8", "store32"):
        return (ins[1], ins[3])
    if op == "call":
        return tuple(ins[3])
    if op == "callind":
        return (ins[2], *ins[3])
    if op in ("retain", "release"):
        return (ins[2],)
    if op == "br":
        return (ins[1],)
    if op in ("brc", "ibr", "fbr"):
        return (ins[2], ins[3])
    if op in ("brci", "brti", "ibri"):
        return (ins[2],)
    if op == "ret":
        return (ins[1],) if ins[1] is not None else ()
    return ()


def map_uses(ins, f):
    """Return ins with every used vreg v replaced by f(v)."""
    op = ins[0]
    if op in ("mov", "i2f", "f2i", "ineg"):
        return (op, ins[1], f(ins[2]))
    if op in ("bin", "cmp", "fbin", "fcmp", "iop", "icmp"):
        return (op, ins[1], ins[2], f(ins[3]), f(ins[4]), *ins[5:])
    if op in ("bini", "bink", "cmpi", "fun", "iopi", "icmpi"):
        return (op, ins[1], ins[2], f(ins[3]), *ins[4:])
    if op == "fpow":
        return (op, ins[1], f(ins[2]), f(ins[3]))
    if op in ("load", "load8", "load32"):
        return (op, ins[1], f(ins[2]), ins[3])
    if op in ("store", "store8", "store32"):
        return (op, f(ins[1]), ins[2], f(ins[3]))
    if op == "call":
        return (op, ins[1], ins[2], [f(a) for a in ins[3]])
    if op == "callind":
        return (op, ins[1], f(ins[2]), [f(a) for a in ins[3]])
    if op in ("retain", "release"):
        return (op, ins[1], f(ins[2]))
    if op == "br":
        return (op, f(ins[1]), ins[2], ins[3])
    if op in ("brc", "ibr", "fbr"):
        return (op, ins[1], f(ins[2]), f(ins[3]), ins[4], ins[5])
    if op in ("brci", "brti", "ibri"):
        return (op, ins[1], f(ins[2]), *ins[3:])
    if op == "ret" and ins[1] is not None:
        return (op, f(ins[1]))
    return ins


def branch_targets(ins):
    op = ins[0]
    if op == "jmp":
        return (ins[1],)
    if op == "br":
        return (ins[2], ins[3])
    if op in ("brc", "brci", "brti", "ibr", "ibri", "fbr"):
        return (ins[4], ins[5])
    return ()


# ---- pass 1: block-local folding --------------------------------------------------------------
def fold(code):
    out = []
    known = {}                      # vreg -> ("k", imm) | ("addc", x, c) | ("copy", s) | ("small",)

    def const_of(v):
        k = known.get(v)
        return k[1] if k and k[0] == "k" else None

    def small(v):
        k = known.get(v)
        return bool(k) and (k[0] == "small" or (k[0] == "k" and k[1] & 1 == 1))

    def resolve(v):
        k = known.get(v)
        return k[1] if k and k[0] == "copy" else v

    def kill(d):
        known.pop(d, None)
        dead = [v for v, k in known.items() if k[0] in ("addc", "copy") and k[1] == d]
        for v in dead:
            del known[v]

    for ins in code:
        op = ins[0]
        if op == "label":
            known.clear()
            out.append(ins)
            continue
        ins = map_uses(ins, resolve)
        op = ins[0]
        if op == "mov":
            c = const_of(ins[2])
            if c is not None:
                ins = ("const", ins[1], c)
            elif ins[1] == ins[2]:
                continue
        elif op == "bin":
            _, bop, d, x, y = ins
            cx, cy = const_of(x), const_of(y)
            if cx is not None and cy is not None and bop in BINI_OPS:
                ins = ("const", d, fold_bin(bop, cx, cy))
            elif cy is not None and bop in BINI_OPS and fits(cy):
                ins = ("bini", bop, d, x, cy)
            elif cy is not None and bop in ("udiv", "urem", "sdiv", "srem") and 0 < cy < 2 ** 63:
                ins = ("bink", bop, d, x, cy)
            elif cx is not None and bop in COMMUTATIVE and fits(cx):
                ins = ("bini", bop, d, y, cx)
        elif op == "cmp":
            _, cc, d, x, y = ins
            cx, cy = const_of(x), const_of(y)
            if cx is not None and cy is not None:
                ins = ("const", d, int(compare(cc, cx, cy)))
            elif cy is not None and fits(cy):
                ins = ("cmpi", cc, d, x, cy)
            elif cx is not None and fits(cx):
                ins = ("cmpi", SWAP[cc], d, y, cx)
        elif op in ("load", "load8", "load32"):
            k = known.get(ins[2])
            if k and k[0] == "addc" and fits(ins[3] + k[2]):
                ins = (op, ins[1], k[1], ins[3] + k[2])
        elif op in ("store", "store8", "store32"):
            k = known.get(ins[1])
            if k and k[0] == "addc" and fits(ins[2] + k[2]):
                ins = (op, k[1], ins[2] + k[2], ins[3])
        elif op == "iop":
            _, iop, d, x, y, span = ins
            cy, cx = const_of(y), const_of(x)
            if cy is not None and cy & 1 and fits(cy) and not (iop in ("div", "mod") and cy == 1):
                ins = ("iopi", iop, d, x, cy, span)
            elif cx is not None and cx & 1 and fits(cx) and iop in ("add", "mul"):
                ins = ("iopi", iop, d, y, cx, span)
        elif op == "fcmp":
            _, cc, d, x, y = ins
            cx, cy = const_of(x), const_of(y)
            if cx is not None and cy is not None:
                ins = ("const", d, int(compare(cc, as_float(cx), as_float(cy))))
        elif op == "br":
            c = const_of(ins[1])
            if c is not None:
                ins = ("jmp", ins[2] if c else ins[3])
        elif op == "icmp":
            _, cc, d, x, y = ins
            cx, cy = const_of(x), const_of(y)
            if cx is not None and cy is not None and cx & 1 and cy & 1:
                ins = ("const", d, int(compare(cc, cx, cy)))
            elif cy is not None and cy & 1 and fits(cy):
                ins = ("icmpi", cc, d, x, cy)
            elif cx is not None and cx & 1 and fits(cx):
                ins = ("icmpi", SWAP[cc], d, y, cx)
        elif op in ("retain", "release") and ins[1] == "int" and small(ins[2]):
            continue
        # record what this instruction defines
        for d in defs(ins):
            kill(d)
        op = ins[0]
        if op == "const":
            known[ins[1]] = ("k", ins[2])
        elif op == "bini" and ins[1] in ("add", "sub") and ins[3] != ins[2]:
            known[ins[2]] = ("addc", ins[3], ins[4] if ins[1] == "add" else -ins[4])
        elif op == "mov" and ins[1] != ins[2]:
            known[ins[1]] = ("copy", ins[2])
        elif op == "iopi" and ins[1] == "mod":
            known[ins[2]] = ("small",)
        elif op in ("cmp", "cmpi", "fcmp"):
            pass
        out.append(ins)
        if op in TERMINATORS:
            known.clear()
    return out


def as_float(w):
    import struct
    return struct.unpack("<d", struct.pack("<q", w))[0]


def compare(cc, a, b):
    if cc.startswith("u"):
        a, b, cc = a & ((1 << 64) - 1), b & ((1 << 64) - 1), cc[1:]
    return {"eq": a == b, "ne": a != b, "lt": a < b, "le": a <= b, "gt": a > b, "ge": a >= b}[cc]


def fold_bin(op, a, b):
    if op == "add":
        return wrap(a + b)
    if op == "sub":
        return wrap(a - b)
    if op == "mul":
        return wrap(a * b)
    if op == "and":
        return wrap(a & b)
    if op == "or":
        return wrap(a | b)
    if op == "xor":
        return wrap(a ^ b)
    if op == "shl":
        return wrap(a << (b & 63))
    if op == "shr":
        return wrap((a & ((1 << 64) - 1)) >> (b & 63))
    if op == "sar":
        return wrap(a >> (b & 63))
    raise ValueError(op)


# ---- pass 2: compare + branch fusion ------------------------------------------------------------
def use_counts(code):
    n = {}
    for ins in code:
        for u in uses(ins):
            n[u] = n.get(u, 0) + 1
    return n


def fuse(fn, code):
    n = use_counts(code)
    out, tail = [], []
    i = 0
    while i < len(code):
        ins = code[i]
        op = ins[0]
        if op == "bini" and ins[1] == "and" and 0 < ins[4] < 256 and n.get(ins[2], 0) == 1 and \
                i + 1 < len(code) and code[i + 1][0] == "br" and code[i + 1][1] == ins[2]:
            out.append(("brti", "ne", ins[3], ins[4], code[i + 1][2], code[i + 1][3]))
            i += 2
            continue
        if op in ("cmp", "cmpi", "icmp", "icmpi", "fcmp") and n.get(ins[2], 0) == 1 and \
                not (op == "fcmp" and ins[1] in ("eq", "ne")):
            d = ins[2]
            operands = set(uses(ins))
            j = i + 1
            mid, releases, ok = [], [], True
            while j < len(code):
                m = code[j]
                if m[0] == "br":
                    break
                if m[0] == "release":
                    releases.append(m)
                elif m[0] in PURE and d not in uses(m) and not (set(defs(m)) & (operands | {d})):
                    mid.append(m)
                else:
                    ok = False
                    break
                j += 1
            if ok and j < len(code) and code[j][1] == d:
                _, _, lt, lf = code[j]
                cc = ins[1]
                x = ins[3]
                y = ins[4]
                kind = {"cmp": "brc", "cmpi": "brci", "icmp": "ibr", "icmpi": "ibri", "fcmp": "fbr"}[op]
                out.extend(mid)
                if releases:
                    lt2, lf2 = fn.label("rt"), fn.label("rf")
                    out.append((kind, cc, x, y, lt2, lf2))
                    out.append(("label", lt2))
                    out.extend(releases)
                    out.append(("jmp", lt))
                    tail.append(("label", lf2))
                    tail.extend(releases)
                    tail.append(("jmp", lf))
                else:
                    out.append((kind, cc, x, y, lt, lf))
                i = j + 1
                continue
        out.append(ins)
        i += 1
    return out + tail


# ---- pass 3: dead code --------------------------------------------------------------------------
def unreachable(code):
    """Drop basic blocks that cannot be reached from the function entry."""
    starts = [0]
    for i, ins in enumerate(code):
        if i and (ins[0] == "label" or code[i - 1][0] in TERMINATORS):
            starts.append(i)
    starts = sorted(set(starts))
    ranges = [(s, starts[k + 1] if k + 1 < len(starts) else len(code)) for k, s in enumerate(starts)]
    at_label = {code[s][1]: k for k, (s, _) in enumerate(ranges) if s < len(code) and code[s][0] == "label"}
    seen, work = set(), [0]
    while work:
        k = work.pop()
        if k in seen or k >= len(ranges):
            continue
        seen.add(k)
        s, e = ranges[k]
        last = code[e - 1] if e > s else None
        if last is None or last[0] not in TERMINATORS:
            work.append(k + 1)
        if last is not None:
            work.extend(at_label[t] for t in branch_targets(last) if t in at_label)
    return [ins for k, (s, e) in enumerate(ranges) if k in seen for ins in code[s:e]]


def dce(code):
    while True:
        n = use_counts(code)
        new = [ins for ins in code if not (ins[0] in PURE and all(n.get(d, 0) == 0 for d in defs(ins)))]
        out = unreachable(new) if new else new
        if len(out) == len(code):
            return out
        code = out


# ---- pass 0: coalesce `X t, ...; mov v, t` into `X v, ...` (t used only by the mov) ------------
COALESCE = {"const", "addr", "bin", "bini", "bink", "cmp", "cmpi", "fbin", "fcmp", "i2f", "f2i", "fun", "fpow",
            "load", "load8", "load32", "iop", "iopi", "icmp", "icmpi", "ineg", "call", "callind"}


def set_def(ins, v):
    op = ins[0]
    if op in ("const", "addr", "i2f", "f2i", "ineg", "fpow", "load", "load8", "load32", "call", "callind"):
        return (op, v, *ins[2:])
    return (op, ins[1], v, *ins[3:])


def coalesce(code):
    n = use_counts(code)
    out = []
    i = 0
    while i < len(code):
        ins = code[i]
        nxt = code[i + 1] if i + 1 < len(code) else None
        if nxt is not None and nxt[0] == "mov" and ins[0] in COALESCE:
            ds = defs(ins)
            if ds and ds[0] == nxt[2] and n.get(nxt[2], 0) == 1 and nxt[1] != nxt[2]:
                out.append(set_def(ins, nxt[1]))
                i += 2
                continue
        out.append(ins)
        i += 1
    return out


def optimize(fn):
    code = coalesce(fn.code)
    code = fold(code)
    code = dce(code)
    code = fuse(fn, code)
    code = dce(code)
    fn.code = code
    return fn


# ---- inlining of small runtime helpers ------------------------------------------------------------
INLINE_MAX = 24          # instructions


def inlinable(fn):
    if len(fn.code) > INLINE_MAX or not fn.code:
        return False
    for ins in fn.code:
        if ins[0] in ("enter", "leave", "site"):
            return False             # functions with shadow-stack frames keep them (error traces)
        if ins[0] == "call" and ins[2] == fn.name:
            return False
    return True


def inline_calls(fns, rounds=2):
    """Replace calls to small frame-less functions (runtime accessors like list_at, g(), str_new)
    by their bodies. Vregs and labels of the callee are renamed into the caller."""
    for _ in range(rounds):
        small = {f.name: f for f in fns if inlinable(f)}
        changed = False
        for f in fns:
            if not any(ins[0] == "call" and ins[2] in small and ins[2] != f.name and
                       len(ins[3]) == small[ins[2]].nparams for ins in f.code):
                continue
            out = []
            for ins in f.code:
                if not (ins[0] == "call" and ins[2] in small and ins[2] != f.name and
                        len(ins[3]) == small[ins[2]].nparams):
                    out.append(ins)
                    continue
                callee = small[ins[2]]
                changed = True
                base = f.nregs
                f.nregs += callee.nregs
                f._labels += 1
                tag = f"{f.name}.in{f._labels}."
                end = "." + tag + "end"
                ren = lambda v, base=base: None if v is None else base + v   # noqa: E731
                lab = lambda name, tag=tag: "." + tag + name.lstrip(".")       # noqa: E731
                for i, a in enumerate(ins[3]):
                    out.append(("mov", base + i, a))
                body = callee.code
                for k, c in enumerate(body):
                    op = c[0]
                    if op == "ret":
                        if ins[1] is not None and c[1] is not None:
                            out.append(("mov", ins[1], base + c[1]))
                        if k != len(body) - 1:
                            out.append(("jmp", end))
                        continue
                    c = rename(c, ren, lab)
                    if c[0] == "call" and c[2] not in small and not c[2].startswith("cold:"):
                        # a call inside an inlined runtime accessor is its slow path (bignum, growth, ...)
                        c = (c[0], c[1], "cold:" + c[2], c[3])
                    out.append(c)
                out.append(("label", end))
            f.code = out
        if not changed:
            return


def rename(ins, ren, lab):
    op = ins[0]
    if op == "label":
        return (op, lab(ins[1]))
    if op == "jmp":
        return (op, lab(ins[1]))
    ins = map_uses(ins, ren)
    # rename the defined register(s)
    if op in ("const", "fp", "mov", "addr", "i2f", "f2i", "ineg", "fpow", "load", "load8", "load32"):
        ins = (op, ren(ins[1]), *ins[2:])
    elif op in ("bin", "bini", "bink", "cmp", "cmpi", "fbin", "fcmp", "fun", "iop", "iopi", "icmp", "icmpi"):
        ins = (op, ins[1], ren(ins[2]), *ins[3:])
    elif op in ("call", "callind"):
        ins = (op, ren(ins[1]), *ins[2:])
    if op == "br":
        ins = (op, ins[1], lab(ins[2]), lab(ins[3]))
    elif op in ("brc", "brci", "brti", "ibr", "ibri", "fbr"):
        ins = (*ins[:4], lab(ins[4]), lab(ins[5]))
    return ins
