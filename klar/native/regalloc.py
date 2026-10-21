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
"""
from bisect import bisect_right

from .opt import NO_CALL, TERMINATORS, branch_targets, defs, uses
from .x64 import R8, R9, R10, R12, R13, R14, R15, RBX, RDI, RSI

CALLEE_SAVED = [RBX, R12, R13, R14, R15]
CALLER_SAVED = [RSI, RDI, R8, R9, R10]


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
    return lo, hi, weight


def allocate(fn):
    """Returns ({vreg: machine register}, [callee-saved registers used])."""
    lo, hi, weight = intervals(fn)
    calls = [i for i, ins in enumerate(fn.code) if ins[0] not in NO_CALL]

    def crosses(v):
        # a call strictly inside (lo, hi): the value must survive it
        k = bisect_right(calls, lo[v])
        return k < len(calls) and calls[k] < hi[v]

    order = sorted(lo, key=lambda v: (lo[v], hi[v]))
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
    return loc, used
