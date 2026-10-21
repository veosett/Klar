"""Linear-scan register allocation for KIR functions.

Liveness is computed per basic block (classic backward dataflow); each vreg gets one
live interval = the hull of every position where it is live. Intervals are then
assigned to machine registers in start order (Poletto & Sarkar linear scan; when the
registers run out, the interval with the lowest use density — uses weighted by 8^loop depth,
divided by length — is spilled to its stack slot).

  * callee-saved RBX, R12–R15: usable by any interval (saved/restored by the function);
  * caller-saved RSI, RDI, R8–R10: only for intervals that contain no call-like
    instruction (anything that may call out of line: calls, Int slow paths, releases, ...).
RAX, RCX, RDX and R11 stay free as scratch registers for the emitter.

Float values get their own class: XMM2–XMM15 for intervals that cross no call (every XMM register is
caller-saved in the System V ABI, and Klar code never relies on XMM values surviving a call). A value
qualifies when it is computed or consumed mostly by floating-point instructions; XMM0/XMM1 are the
emitter's scratch registers.
"""
from bisect import bisect_right

from .opt import NO_CALL, TERMINATORS, branch_targets, defs, uses
from .x64 import R8, R9, R10, R12, R13, R14, R15, RBX, RDI, RSI

CALLEE_SAVED = [RBX, R12, R13, R14, R15]
CALLER_SAVED = [RSI, RDI, R8, R9, R10]
XMM_REGS = list(range(15, 1, -1))     # XMM2..XMM15 (popped from the end: XMM2 first)
FP_DEF = {"fbin", "i2f", "fun"}
# instructions whose only calls are out-of-line runtime calls (Int slow paths, free, stack overflow): the
# emitter saves the XMM registers around those, so a float may stay in an XMM register across them
XMM_SAFE = {"iop", "iopi", "icmp", "icmpi", "ibr", "ibri", "ineg", "release", "enter"}
FP_USE = {"fbin", "fcmp", "fbr", "f2i", "fun"}


def float_candidates(fn, weight_of):
    """vregs worth keeping in XMM registers: defined or used by float instructions, and used by
    float instructions at least as much (by loop-weighted count) as by anything else."""
    fp_w, other_w, fp_def = {}, {}, set()
    for i, ins in enumerate(fn.code):
        op = ins[0]
        w = weight_of(i)
        if op in FP_DEF:
            fp_def.update(defs(ins))
        for u in uses(ins):
            if op in FP_USE:
                fp_w[u] = fp_w.get(u, 0) + w
            elif op != "mov":
                other_w[u] = other_w.get(u, 0) + w
    out = set()
    for v in set(fp_w) | fp_def:
        if v is None or v < fn.nparams:
            continue
        if fp_w.get(v, 0) >= other_w.get(v, 0) and (v in fp_def or fp_w.get(v, 0) > 0):
            out.add(v)
    # copies between float values stay in the class (loop-carried `var`s are joined by `mov`)
    changed = True
    while changed:
        changed = False
        for ins in fn.code:
            if ins[0] == "mov" and ins[2] in out and ins[1] not in out and ins[1] >= fn.nparams:
                if other_w.get(ins[1], 0) <= fp_w.get(ins[1], 0):
                    out.add(ins[1])
                    changed = True
    return out


def blocks_of(code):
    """[(start, end)] half-open ranges, plus label -> block index."""
    starts = {0}
    for i, ins in enumerate(code):
        if ins[0] == "label":
            starts.add(i)
        elif ins[0] in TERMINATORS and i + 1 < len(code):
            starts.add(i + 1)
    order = sorted(s for s in starts if s < len(code))
    blocks = [(s, order[k + 1] if k + 1 < len(order) else len(code)) for k, s in enumerate(order)]
    label_block = {}
    for b, (s, _) in enumerate(blocks):
        if code[s][0] == "label":
            label_block[code[s][1]] = b
    return blocks, label_block


def intervals(fn):
    code = fn.code
    blocks, label_block = blocks_of(code)
    nb = len(blocks)
    succ = []
    gen, kill = [], []
    for b, (s, e) in enumerate(blocks):
        last = code[e - 1] if e > s else ("label", None)
        if last[0] in TERMINATORS:
            succ.append([label_block[t] for t in branch_targets(last) if t in label_block])
        else:
            succ.append([b + 1] if b + 1 < nb else [])
        g, k = set(), set()
        for ins in code[s:e]:
            for u in uses(ins):
                if u not in k:
                    g.add(u)
            k.update(defs(ins))
        gen.append(g)
        kill.append(k)
    live_in = [set() for _ in range(nb)]
    live_out = [set() for _ in range(nb)]
    changed = True
    while changed:
        changed = False
        for b in range(nb - 1, -1, -1):
            out = set()
            for t in succ[b]:
                out |= live_in[t]
            inn = gen[b] | (out - kill[b])
            if out != live_out[b] or inn != live_in[b]:
                live_out[b], live_in[b] = out, inn
                changed = True
    lo, hi = {}, {}

    def ext(v, p):
        if v is None:
            return
        if v not in lo or p < lo[v]:
            lo[v] = p
        if v not in hi or p > hi[v]:
            hi[v] = p

    # spill weights: every use/def counts 8^loop_depth
    depth = [0] * (len(code) + 1)
    pos = {ins[1]: i for i, ins in enumerate(code) if ins[0] == "label"}
    for j, ins in enumerate(code):
        for t in branch_targets(ins):
            i = pos.get(t)
            if i is not None and i <= j:
                for k in range(i, j + 1):
                    depth[k] += 1
    weight = {}
    for i, ins in enumerate(code):
        w = 8 ** min(depth[i], 6)
        for v in (*uses(ins), *defs(ins)):
            if v is not None:
                weight[v] = weight.get(v, 0) + w
    for p in range(fn.nparams):
        ext(p, -1)
    for b, (s, e) in enumerate(blocks):
        for v in live_in[b]:
            ext(v, s)
        for v in live_out[b]:
            ext(v, e - 1)
        for i in range(s, e):
            ins = code[i]
            for u in uses(ins):
                ext(u, i)
            for d in defs(ins):
                ext(d, i)
    fn.depth = depth
    return lo, hi, weight


def allocate_xmm(fn, lo, hi, weight, crosses):
    cands = float_candidates(fn, lambda i: 8 ** min(fn.depth[i], 6))
    cands = [v for v in cands if v in lo and not crosses(v)]
    free = list(XMM_REGS)
    active = []
    xloc = {}
    for v in sorted(cands, key=lambda v: (lo[v], hi[v])):
        still = []
        for end, w in active:
            if end < lo[v]:
                free.append(xloc[w])
            else:
                still.append((end, w))
        active = still
        if not free:
            def cost(u):
                return weight.get(u, 0) / (hi[u] - lo[u] + 1)
            end, w = min(active, key=lambda c: cost(c[1]))
            if cost(w) >= cost(v):
                continue
            free.append(xloc.pop(w))
            active.remove((end, w))
        xloc[v] = free.pop()
        active.append((hi[v], v))
    return xloc


def allocate(fn):
    """Returns ({vreg: register}, [callee-saved registers used], {vreg: XMM register})."""
    lo, hi, weight = intervals(fn)
    calls = [i for i, ins in enumerate(fn.code) if ins[0] not in NO_CALL]

    def crosses(v):
        # a call strictly inside (lo, hi): the value must survive it
        k = bisect_right(calls, lo[v])
        return k < len(calls) and calls[k] < hi[v]

    real_calls = [i for i, ins in enumerate(fn.code) if ins[0] not in NO_CALL and ins[0] not in XMM_SAFE]

    def crosses_real(v):
        k = bisect_right(real_calls, lo[v])
        return k < len(real_calls) and real_calls[k] < hi[v]

    xloc = allocate_xmm(fn, lo, hi, weight, crosses_real)
    order = sorted((v for v in lo if v not in xloc), key=lambda v: (lo[v], hi[v]))
    free_callee = list(CALLEE_SAVED)
    free_caller = list(CALLER_SAVED)
    active = []                    # (hi, v)
    loc = {}
    for v in order:
        start = lo[v]
        still = []
        for end, w in active:
            if end < start:
                r = loc[w]
                (free_callee if r in CALLEE_SAVED else free_caller).append(r)
            else:
                still.append((end, w))
        active = still
        need_callee = crosses(v)
        reg = None
        if not need_callee and free_caller:
            reg = free_caller.pop()
        elif free_callee:
            reg = free_callee.pop()
        if reg is None:
            # spill the (compatible) interval with the lowest weight per instruction covered
            def cost(u):
                return weight.get(u, 0) / (hi[u] - lo[u] + 1)
            cands = [(end, w) for end, w in active if not need_callee or loc[w] in CALLEE_SAVED]
            if not cands:
                continue
            end, w = min(cands, key=lambda c: cost(c[1]))
            if cost(w) >= cost(v):
                continue                          # v is the cheapest: it stays in memory
            reg = loc.pop(w)
            active.remove((end, w))
        loc[v] = reg
        active.append((hi[v], v))
    used = sorted({r for r in loc.values() if r in CALLEE_SAVED})
    return loc, used, xloc
