"""KIR -> x86-64 machine code, plus the per-OS layer (Linux syscalls / Windows kernel32).

Calling convention (Klar internal): the caller reserves an argument area of 8*n bytes
(rounded up to 16) at [rsp], stores argument i at [rsp+8*i] and calls; the callee
reads it at [rbp+16+8*i]. The result is returned in rax. RBX and R12-R14 are
callee-saved; RAX, RCX, RDX, RSI, RDI, R8-R11 may be clobbered by a call. R15 is reserved in all
generated code: it counts the nesting depth of Klar calls (R0006 above 10000), which costs two register
instructions per call instead of a load/store pair on a global.

Each function is first optimized (opt.py) and register-allocated (regalloc.py): vregs
live in machine registers where possible and in stack slots otherwise. Int slow paths,
division-by-zero and freeing are emitted out of line after the function body.
"""
from .x64 import (Asm, RAX, RCX, RDX, RBX, RSP, RBP, RSI, RDI, R8, R9, R10, R11, R15, XMM0, XMM1)

MAX_DEPTH = 10000

OS_FUNCS = ["os_write", "os_read", "os_exit", "os_alloc", "os_time_ns", "os_wall_ns", "os_open", "os_close",
            "os_file_exists", "os_argc", "os_argv", "os_cmdline", "os_platform", "os_getenv", "os_spawn", "os_chmod"]

WIN_IMPORTS = ["GetStdHandle", "WriteFile", "ReadFile", "ExitProcess", "VirtualAlloc", "QueryPerformanceCounter",
               "QueryPerformanceFrequency", "CreateFileA", "CloseHandle", "GetFileAttributesA", "GetCommandLineA",
               "SetConsoleOutputCP", "GetEnvironmentVariableA", "GetSystemTimeAsFileTime", "CreateProcessA",
               "WaitForSingleObject", "GetExitCodeProcess"]


def udiv_magic(d):
    """(m, l) with x // d == (t + ((x - t) >> 1)) >> (l - 1), t = mulhi(m, x), for all 64-bit x (d >= 3)."""
    l = (d - 1).bit_length()
    return (1 << (64 + l)) // d - (1 << 64) + 1, l


def udiv_magic_simple(d):
    """(m, s) with x // d == mulhi(m, x) >> s for all 64-bit x, when such an m < 2^64 exists."""
    for s in range(64):
        m = -(-(1 << (64 + s)) // d)
        if m >= 1 << 64:
            return None
        if m * d - (1 << (64 + s)) <= 1 << s:
            return m, s
    return None


def sdiv_magic64(d):
    """Hacker's Delight signed magic number for 64-bit division by d >= 3 (not a power of two):
    q = (mulhs(M, n) [+ n if M < 0]) >> s, then +1 if q < 0."""
    two63 = 1 << 63
    anc = two63 - 1 - two63 % d
    p = 63
    q1, r1 = divmod(two63, anc)
    q2, r2 = divmod(two63, d)
    while True:
        p += 1
        q1, r1 = 2 * q1, 2 * r1
        if r1 >= anc:
            q1, r1 = q1 + 1, r1 - anc
        q2, r2 = 2 * q2, 2 * r2
        if r2 >= d:
            q2, r2 = q2 + 1, r2 - d
        delta = d - r2
        if not (q1 < delta or (q1 == delta and r1 == 0)):
            break
    m = (q2 + 1) & ((1 << 64) - 1)
    if m >= 1 << 63:
        m -= 1 << 64
    return m, p - 64


def sdiv_magic(d):
    """(m, s): floor(a*m / 2^(64+s)) == floor(a / d) for |a| <= 2^62, d >= 3 not a power of two."""
    l = (d - 1).bit_length()
    p = 62 + l
    return -(-(1 << p) // d), p - 64


def align16(n):
    return (n + 15) // 16 * 16


class Emitter:
    def __init__(self, image, target, rt):
        self.img = image
        self.target = target       # "linux" | "windows"
        self.rt = rt               # name of runtime helper -> KIR function name
        self.a = Asm()
        self.user_fns = []         # (start label, end label, name symbol) of Klar functions with frames
        self.call_sites = []       # (return-address label, span symbol or None) inside those functions
        self.user = False
        self.cur_site = None

    # ---- locations ---------------------------------------------------------------
    # A vreg lives either in a machine register (self.loc[v]) or in its stack slot.
    def slot(self, fn, v):
        if v < fn.nparams:
            return 16 + 8 * v
        return -8 * (v - fn.nparams + 1)

    def ld(self, reg, fn, v):
        r = self.loc.get(v)
        if r is None:
            self.a.load(reg, RBP, self.slot(fn, v))
        else:
            self.a.mov_rr(reg, r)

    def st(self, fn, v, reg):
        r = self.loc.get(v)
        if r is None:
            self.a.store(RBP, self.slot(fn, v), reg)
        else:
            self.a.mov_rr(r, reg)

    def src(self, fn, v, scratch):
        """A register holding v (its own register, or `scratch` after loading)."""
        r = self.loc.get(v)
        if r is not None:
            return r
        self.a.load(scratch, RBP, self.slot(fn, v))
        return scratch

    def dst(self, v, scratch):
        """The register to compute v into; finish with fin()."""
        return self.loc.get(v, scratch)

    def fin(self, fn, v, reg):
        if v not in self.loc:
            self.a.store(RBP, self.slot(fn, v), reg)

    def mem(self, fn, v, which=0):
        """(base, disp) of v in memory — a scratch slot when v lives in a register."""
        r = self.loc.get(v)
        if r is None:
            return RBP, self.slot(fn, v)
        off = self.scratch_off - 8 * which
        self.a.store(RBP, off, r)
        return RBP, off

    # ---- functions -------------------------------------------------------------
    def function(self, fn):
        from .opt import optimize
        from .regalloc import allocate
        optimize(fn)
        self.loc, self.saved, self.xloc = allocate(fn)
        self.slot_needed = self.xmm_slot_needed(fn)
        a = self.a
        enter = next((ins for ins in fn.code if ins[0] == "enter"), None)
        self.user = enter is not None
        self.cur_site = None
        a.label(fn.name)
        a.push(RBP)
        a.mov_rr(RBP, RSP)
        base = 8 * max(fn.nregs - fn.nparams, 0)
        self.save_off = [-(base + 8 * (k + 1)) for k in range(len(self.saved))]
        self.scratch_off = -(base + 8 * (len(self.saved) + 1))
        self.xmm_used = sorted(set(self.xloc.values()))
        self.xsave_off = [self.scratch_off - 16 - 8 * k for k in range(len(self.xmm_used))]
        self.call_saves = getattr(fn, "call_saves", {})
        csave = sorted({r for regs in self.call_saves.values() for r in regs})
        first = self.scratch_off - 16 - 8 * len(self.xmm_used)
        self.csave_off = {r: first - 8 * k for k, r in enumerate(csave)}
        self.cur_saves = ()
        frame = align16(base + 8 * (len(self.saved) + 2 + len(self.xmm_used) + len(csave)))
        a.alu_ri("sub", RSP, frame)
        for r, off in zip(self.saved, self.save_off):
            a.store(RBP, off, r)
        for p in range(fn.nparams):
            if p in self.loc:
                a.load(self.loc[p], RBP, self.slot(fn, p))
        self.cold = []
        code = fn.code
        for k, ins in enumerate(code):
            nxt = code[k + 1] if k + 1 < len(code) else None
            self.next_label = nxt[1] if nxt is not None and nxt[0] == "label" else None
            self.cur_saves = sorted(self.call_saves.get(k, ()))
            n_cold = len(self.cold)
            getattr(self, "i_" + ins[0])(fn, *ins[1:])
            if self.cur_saves:
                for j in range(n_cold, len(self.cold)):   # out-of-line code runs later: keep its save set
                    self.cold[j] = self.with_saves(self.cold[j], self.cur_saves)
            if self.xloc and ins[0] not in self.XMM_AWARE:
                # an instruction that knows nothing about XMM wrote the value to its slot: refresh the register
                from .opt import defs
                for d in defs(ins):
                    if d in self.xloc:
                        a.movsd_load(self.xloc[d], RBP, self.slot(fn, d))
        # safety net: a function body always ends with an explicit ret
        a.ud2()
        self.next_label = None
        for emit_cold in self.cold:
            emit_cold()
        a.ud2()
        if self.user:
            end = f".fnend.{fn.name}"
            a.label(end)
            self.user_fns.append((fn.name, end, enter[1]))

    def with_saves(self, emit_cold, saves):
        def run():
            old, self.cur_saves = self.cur_saves, saves
            try:
                emit_cold()
            finally:
                self.cur_saves = old
        return run

    def save_live(self):
        for r in self.cur_saves:
            self.a.store(RBP, self.csave_off[r], r)

    def restore_live(self):
        for r in self.cur_saves:
            self.a.load(r, RBP, self.csave_off[r])

    def emit_call(self, fn, target, args, indirect_reg_of=None):
        a = self.a
        self.save_live()
        area = align16(8 * len(args))
        if area:
            a.alu_ri("sub", RSP, area)
        for i, v in enumerate(args):
            a.store(RSP, 8 * i, self.src(fn, v, RAX))
        if indirect_reg_of is not None:
            self.ld(R11, fn, indirect_reg_of)
            a.call_r(R11)
        else:
            a.call(target)
        self.note_site()
        if area:
            a.alu_ri("add", RSP, area)
        self.restore_live()

    def note_site(self):
        """Remember the return address of a call inside a Klar function and its source span:
        error traces walk the RBP chain and map return addresses back to call sites (no run-time cost)."""
        if self.user:
            lab = self.a.new_label("ra")
            self.a.label(lab)
            self.call_sites.append((lab, self.cur_site))

    def call_rt(self, fn, name, regs_values):
        """Call a runtime helper with values already in machine registers (pushed in order). These calls sit
        on out-of-line paths, so they also save and restore the XMM registers holding floats."""
        a = self.a
        for x, off in zip(self.xmm_used, self.xsave_off):
            a.movsd_store(RBP, off, x)
        self.save_live()
        area = align16(8 * len(regs_values))
        if area:
            a.alu_ri("sub", RSP, area)
        for i, r in enumerate(regs_values):
            a.store(RSP, 8 * i, r)
        a.call(self.rt[name])
        self.note_site()
        if area:
            a.alu_ri("add", RSP, area)
        self.restore_live()
        for x, off in zip(self.xmm_used, self.xsave_off):
            a.movsd_load(x, RBP, off)

    # ---- branches ------------------------------------------------------------------
    NEG = {"e": "ne", "ne": "e", "l": "ge", "ge": "l", "le": "g", "g": "le", "b": "ae", "ae": "b",
           "be": "a", "a": "be"}

    def branch(self, cc, lt, lf):
        """Flags are set; jump to lt if cc holds, else to lf (falling through when possible)."""
        a = self.a
        if self.next_label == lf:
            a.jcc(cc, lt)
        elif self.next_label == lt:
            a.jcc(self.NEG[cc], lf)
        else:
            a.jcc(cc, lt)
            a.jmp(lf)

    # ---- floats in XMM registers -------------------------------------------------------
    # A value in self.xloc lives in an XMM register. Its stack slot is kept current too (written through)
    # whenever some instruction reads it the generic way, so every other instruction stays correct.
    XMM_AWARE = {"fbin", "fcmp", "fbr", "i2f", "f2i", "const", "mov", "fun"}

    def xmm_slot_needed(self, fn):
        from .opt import uses
        need = set()
        if not self.xloc:
            return need
        for ins in fn.code:
            op = ins[0]
            if op in ("fbin", "fcmp", "fbr", "f2i", "mov") or (op == "fun" and ins[1] == "sqrt"):
                continue
            for u in uses(ins):
                if u in self.xloc:
                    need.add(u)
        return need

    def xsrc(self, fn, v, scratch):
        """An XMM register holding the float v."""
        x = self.xloc.get(v)
        if x is not None:
            return x
        r = self.loc.get(v)
        if r is None:
            self.a.movsd_load(scratch, RBP, self.slot(fn, v))
        else:
            self.a.movq_xr(scratch, r)
        return scratch

    def xfin(self, fn, d, x):
        """Store the float result held in XMM register x into d."""
        xd = self.xloc.get(d)
        if xd is not None:
            self.a.movapd(xd, x)
            if d in self.slot_needed:
                self.a.movsd_store(RBP, self.slot(fn, d), xd)
            return
        r = self.loc.get(d)
        if r is None:
            self.a.movsd_store(RBP, self.slot(fn, d), x)
        else:
            self.a.movq_rx(r, x)

    def xtarget(self, d, *avoid):
        """The XMM register to compute d in (its own one, unless an operand still needs it)."""
        xd = self.xloc.get(d)
        return xd if xd is not None and xd not in avoid else XMM0

    # ---- instructions ------------------------------------------------------------
    def i_const(self, fn, d, imm):
        if d in self.xloc:
            self.a.mov_ri(RAX, imm)
            self.a.movq_xr(self.xloc[d], RAX)
            if d in self.slot_needed:
                self.a.store(RBP, self.slot(fn, d), RAX)
            return
        r = self.dst(d, RAX)
        self.a.mov_ri(r, imm)
        self.fin(fn, d, r)

    def i_mov(self, fn, d, s):
        if d == s:
            return
        if d in self.xloc or s in self.xloc:
            if d in self.xloc:
                self.xfin(fn, d, self.xsrc(fn, s, XMM0))
            elif d in self.loc:
                self.a.movq_rx(self.loc[d], self.xloc[s])
            else:
                self.a.movsd_store(RBP, self.slot(fn, d), self.xloc[s])
            return
        rd = self.loc.get(d)
        if rd is not None:
            self.ld(rd, fn, s)
        else:
            self.st(fn, d, self.src(fn, s, RAX))

    def i_addr(self, fn, d, sym):
        r = self.dst(d, RAX)
        self.a.lea_rip(r, sym)
        self.fin(fn, d, r)

    def i_bin(self, fn, op, d, x, y):
        a = self.a
        if op in ("add", "sub", "and", "or", "xor", "mul"):
            r = self.dst(d, RAX)
            if self.loc.get(y) == r and r is not None and d != x:
                r = RAX                         # d shares y's register: compute in scratch
            ry = self.src(fn, y, RCX)
            if r == ry:                         # d == y == x? (all one vreg) -> scratch copy
                a.mov_rr(RCX, ry)
                ry = RCX
            self.ld(r, fn, x)
            if op == "mul":
                a.imul_rr(r, ry)
            else:
                a.alu_rr(op, r, ry)
            self.st(fn, d, r)
            return
        self.ld(RAX, fn, x)
        self.ld(RCX, fn, y)
        if op in ("sdiv", "srem"):
            a.cqo()
            a.idiv(RCX)
            if op == "srem":
                a.mov_rr(RAX, RDX)
        elif op in ("udiv", "urem"):
            a.alu_rr("xor", RDX, RDX)
            a.div(RCX)
            if op == "urem":
                a.mov_rr(RAX, RDX)
        elif op in ("shl", "shr", "sar"):
            a.shift_cl(op, RAX)
        elif op == "umulhi":
            a.mul(RCX)
            a.mov_rr(RAX, RDX)
        else:
            raise ValueError(op)
        self.st(fn, d, RAX)

    def i_bini(self, fn, op, d, x, imm):
        a = self.a
        r = self.dst(d, RAX)
        self.ld(r, fn, x)
        if op in ("shl", "shr", "sar"):
            a.shift_i(op, r, imm)
        elif op == "mul":
            a.imul_rri(r, r, imm)
        else:
            a.alu_ri(op, r, imm)
        self.fin(fn, d, r)

    def i_bink(self, fn, op, d, x, c):
        """Division / remainder by a positive constant: multiply by the rounded reciprocal."""
        a = self.a
        self.ld(RCX, fn, x)
        if op in ("sdiv", "srem"):
            if c & (c - 1) == 0:
                k = c.bit_length() - 1
                a.mov_rr(RAX, RCX)
                if k:
                    a.shift_i("sar", RAX, 63)
                    a.shift_i("shr", RAX, 64 - k)
                    a.alu_rr("add", RAX, RCX)
                    a.shift_i("sar", RAX, k)      # q = trunc(x / 2^k)
            else:
                m, s = sdiv_magic64(c)
                a.mov_ri(RAX, m)
                a.imul1(RCX)                      # rdx:rax = m * x (signed)
                if m < 0:
                    a.alu_rr("add", RDX, RCX)
                if s:
                    a.shift_i("sar", RDX, s)
                a.mov_rr(RAX, RDX)
                a.shift_i("shr", RAX, 63)
                a.alu_rr("add", RAX, RDX)         # q
            if op == "sdiv":
                self.st(fn, d, RAX)
                return
            a.mov_ri(RDX, c)
            a.imul_rr(RAX, RDX)
            a.alu_rr("sub", RCX, RAX)
            self.st(fn, d, RCX)
            return
        if c & (c - 1) == 0:
            k = c.bit_length() - 1
            if op == "udiv":
                a.shift_i("shr", RCX, k)
            else:
                a.mov_ri(RAX, c - 1)
                a.alu_rr("and", RCX, RAX)
            self.st(fn, d, RCX)
            return
        simple = udiv_magic_simple(c)
        if simple:
            m, s = simple
            a.mov_ri(RAX, m)
            a.mul(RCX)
            a.mov_rr(RAX, RDX)
            if s:
                a.shift_i("shr", RAX, s)   # q
        else:
            m, l = udiv_magic(c)
            a.mov_ri(RAX, m)
            a.mul(RCX)                    # rdx = t = mulhi(m, x)
            a.mov_rr(RAX, RCX)
            a.alu_rr("sub", RAX, RDX)
            a.shift_i("shr", RAX, 1)
            a.alu_rr("add", RAX, RDX)
            a.shift_i("shr", RAX, l - 1)  # q
        if op == "udiv":
            self.st(fn, d, RAX)
            return
        a.mov_ri(RDX, c)
        a.imul_rr(RAX, RDX)
        a.alu_rr("sub", RCX, RAX)
        self.st(fn, d, RCX)

    CCS = {"eq": "e", "ne": "ne", "lt": "l", "le": "le", "gt": "g", "ge": "ge", "ult": "b", "ule": "be",
           "ugt": "a", "uge": "ae"}

    def i_cmp(self, fn, cc, d, x, y):
        a = self.a
        rx = self.src(fn, x, RAX)
        ry = self.src(fn, y, RCX)
        a.alu_rr("cmp", rx, ry)
        r = self.dst(d, RAX)
        a.setcc(self.CCS[cc], r)
        self.fin(fn, d, r)

    def i_cmpi(self, fn, cc, d, x, imm):
        a = self.a
        a.alu_ri("cmp", self.src(fn, x, RAX), imm)
        r = self.dst(d, RAX)
        a.setcc(self.CCS[cc], r)
        self.fin(fn, d, r)

    def i_brc(self, fn, cc, x, y, lt, lf):
        rx = self.src(fn, x, RAX)
        ry = self.src(fn, y, RCX)
        self.a.alu_rr("cmp", rx, ry)
        self.branch(self.CCS[cc], lt, lf)

    def i_brci(self, fn, cc, x, imm, lt, lf):
        self.a.alu_ri("cmp", self.src(fn, x, RAX), imm)
        self.branch(self.CCS[cc], lt, lf)

    def i_brti(self, fn, cc, x, imm, lt, lf):
        self.a.test_ri8(self.src(fn, x, RAX), imm)
        self.branch("ne", lt, lf)

    def fload2(self, fn, x, y):
        return self.xsrc(fn, x, XMM0), self.xsrc(fn, y, XMM1)

    def i_fbin(self, fn, op, d, x, y):
        xa, xb = self.fload2(fn, x, y)
        t = self.xtarget(d, xb)
        self.a.movapd(t, xa)
        self.a.sse(op, t, xb)
        self.xfin(fn, d, t)

    FCC = {"lt": ("a", True), "le": ("ae", True), "gt": ("a", False), "ge": ("ae", False)}

    def i_fcmp(self, fn, cc, d, x, y):
        a = self.a
        xa, xb = self.fload2(fn, x, y)
        if cc in self.FCC:
            c, swap = self.FCC[cc]
            a.ucomisd(xb, xa) if swap else a.ucomisd(xa, xb)
            a.setcc(c, RAX)
        else:
            a.ucomisd(xa, xb)
            a.setcc("e", RAX)
            a.setcc("np", RCX)
            a.alu_rr("and", RAX, RCX)
            if cc == "ne":
                a.alu_ri("xor", RAX, 1)
        self.st(fn, d, RAX)

    def i_fbr(self, fn, cc, x, y, lt, lf):
        a = self.a
        xa, xb = self.fload2(fn, x, y)
        c, swap = self.FCC[cc]
        a.ucomisd(xb, xa) if swap else a.ucomisd(xa, xb)
        self.branch(c, lt, lf)

    def i_i2f(self, fn, d, x):
        t = self.xtarget(d)
        self.a.cvtsi2sd(t, self.src(fn, x, RAX))
        self.xfin(fn, d, t)

    def i_f2i(self, fn, d, x):
        xa = self.xsrc(fn, x, XMM0)
        r = self.dst(d, RAX)
        self.a.cvttsd2si(r, xa)
        self.fin(fn, d, r)

    def fstp_to(self, fn, d):
        a = self.a
        r = self.loc.get(d)
        if r is None:
            a.fstp_m(RBP, self.slot(fn, d))
            if d in self.xloc:
                a.movsd_load(self.xloc[d], RBP, self.slot(fn, d))
        else:
            a.fstp_m(RBP, self.scratch_off)
            a.load(r, RBP, self.scratch_off)

    def i_fun(self, fn, op, d, x):
        a = self.a
        if op == "sqrt":
            xs = self.xsrc(fn, x, XMM1)
            t = self.xtarget(d)
            a.sse("sqrt", t, xs)
            self.xfin(fn, d, t)
            return
        a.fld_m(*self.mem(fn, x))
        if op == "sin":
            a.x87("fsin")
        elif op == "cos":
            a.x87("fcos")
        elif op == "ln":            # ln(x) = ln2 * log2(x)
            a.x87("fldln2")
            a.x87("fxch")
            a.x87("fyl2x")
        elif op == "exp":           # e^x = 2^f * 2^n with y = x*log2(e), n = round(y), f = y - n
            a.x87("fldl2e")
            a.x87("fmulp")          # st0 = y
            a.x87("fld0")           # st0 = y, st1 = y
            a.x87("frndint")        # st0 = n, st1 = y
            a.x87("fxch")           # st0 = y, st1 = n
            a.x87("fsub01")         # st0 = y - n = f
            a.x87("f2xm1")          # st0 = 2^f - 1
            a.x87("fld1")
            a.x87("faddp")          # st0 = 2^f, st1 = n
            a.x87("fscale")         # st0 = 2^f * 2^n
            a.x87("fstp1")          # drop n
        self.fstp_to(fn, d)

    def i_fpow(self, fn, d, x, y):
        """x^y = 2^(y*log2 x) for x > 0, computed in x87 extended precision."""
        a = self.a
        a.fld_m(*self.mem(fn, y, 0))
        a.fld_m(*self.mem(fn, x, 1))
        a.x87("fyl2x")           # st0 = y*log2(x)
        a.x87("fld0")
        a.x87("frndint")         # st0 = n, st1 = z
        a.x87("fxch")            # st0 = z, st1 = n
        a.x87("fsub01")          # st0 = z - n
        a.x87("f2xm1")
        a.x87("fld1")
        a.x87("faddp")
        a.x87("fscale")
        a.x87("fstp1")
        self.fstp_to(fn, d)

    # ---- tagged Int fast paths ------------------------------------------------------
    # Fast paths stay inline; the bignum / error paths are emitted out of line ("cold").
    def int_slow(self, fn, op, d, x, y_reg_loader, done):
        slow = self.a.new_label("islow")

        def cold():
            a = self.a
            a.label(slow)
            self.ld(RAX, fn, x)
            y_reg_loader()
            self.call_rt(fn, "int_" + op, [RAX, RCX])
            self.st(fn, d, RAX)
            a.jmp(done)
        self.cold.append(cold)
        return slow

    def div_check(self, fn, span, divisor_reg):
        a = self.a
        bad = a.new_label("dz")
        a.alu_ri("cmp", divisor_reg, 1)          # tagged zero == 1
        a.jcc("e", bad)

        def cold():
            a.label(bad)
            if span:
                a.lea_rip(RAX, span)
            else:
                a.mov_ri(RAX, 0)
            self.call_rt(fn, "div_zero", [RAX])
            a.ud2()
        self.cold.append(cold)

    def i_iop(self, fn, op, d, x, y, span=None):
        a = self.a
        done = a.new_label("idone")
        slow = self.int_slow(fn, op, d, x, lambda: self.ld(RCX, fn, y), done)
        self.ld(RAX, fn, x)
        self.ld(RCX, fn, y)
        if op in ("div", "mod"):
            self.div_check(fn, span, RCX)
        a.mov_rr(RDX, RAX)
        a.alu_rr("and", RDX, RCX)
        a.test_ri8(RDX, 1)
        a.jcc("e", slow)
        if op == "add":
            a.alu_ri("sub", RCX, 1)
            a.alu_rr("add", RAX, RCX)
            a.jcc("o", slow)
        elif op == "sub":
            a.alu_ri("sub", RCX, 1)
            a.alu_rr("sub", RAX, RCX)
            a.jcc("o", slow)
        elif op == "mul":
            a.shift_i("sar", RAX, 1)
            a.alu_ri("sub", RCX, 1)
            a.imul_rr(RAX, RCX)
            a.jcc("o", slow)
            a.alu_ri("add", RAX, 1)
        elif op in ("div", "mod"):
            a.shift_i("sar", RAX, 1)
            a.shift_i("sar", RCX, 1)
            a.cqo()
            a.idiv(RCX)
            if op == "mod":
                a.mov_rr(RAX, RDX)
            a.alu_rr("add", RAX, RAX)
            a.jcc("o", slow)
            a.alu_ri("add", RAX, 1)
        self.st(fn, d, RAX)
        a.label(done)

    def i_iopi(self, fn, op, d, x, t, span=None):
        """Tagged Int op with the constant small Int t (already tagged: 2c+1)."""
        a = self.a
        done = a.new_label("idone")
        slow = self.int_slow(fn, op, d, x, lambda: a.mov_ri(RCX, t), done)
        rx = self.src(fn, x, RAX)
        a.test_ri8(rx, 1)
        a.jcc("e", slow)
        r = self.dst(d, RAX)
        if r != RAX and op in ("add", "sub") and d != x:
            a.mov_rr(r, rx)
            a.alu_ri(op, r, t - 1)
            a.jcc("o", slow)        # the slow path recomputes from x, which is untouched
            a.label(done)
            return
        a.mov_rr(RAX, rx)
        if op in ("add", "sub"):
            a.alu_ri(op, RAX, t - 1)
            a.jcc("o", slow)
        elif op == "mul":
            a.shift_i("sar", RAX, 1)
            a.imul_rri(RAX, RAX, t - 1)
            a.jcc("o", slow)
            a.alu_ri("add", RAX, 1)
        elif op in ("div", "mod") and abs(t >> 1) >= 2:
            self.const_divmod(op, t >> 1)
        elif op in ("div", "mod"):
            a.shift_i("sar", RAX, 1)
            a.mov_ri(RCX, t >> 1)
            a.cqo()
            a.idiv(RCX)
            if op == "mod":
                a.mov_rr(RAX, RDX)
            a.alu_rr("add", RAX, RAX)
            a.jcc("o", slow)
            a.alu_ri("add", RAX, 1)
        self.st(fn, d, RAX)
        a.label(done)

    def const_divmod(self, op, c):
        """rax = tagged small Int -> tagged (rax / c) or (rax % c), truncating; |c| >= 2.
        Uses a reciprocal multiply (exact for |a| <= 2^62, the small-Int range): no idiv."""
        a = self.a
        a.mov_rr(RCX, RAX)
        a.shift_i("sar", RCX, 1)                  # rcx = a
        ac = abs(c)
        if ac & (ac - 1) == 0:
            k = ac.bit_length() - 1
            a.mov_rr(RAX, RCX)
            a.shift_i("sar", RAX, 63)
            a.shift_i("shr", RAX, 64 - k)
            a.alu_rr("add", RAX, RCX)
            a.shift_i("sar", RAX, k)              # q = trunc(a / 2^k)
        else:
            m, s = sdiv_magic(ac)
            a.mov_ri(RAX, m)
            a.imul1(RCX)                          # rdx:rax = a * m
            if s:
                a.shift_i("sar", RDX, s)
            a.mov_rr(RAX, RCX)
            a.shift_i("shr", RAX, 63)
            a.alu_rr("add", RAX, RDX)             # q = floor(a*m / 2^p) + (a < 0)
        if c < 0:
            a.neg(RAX)
        if op == "mod":
            a.imul_rri(RAX, RAX, c)
            a.alu_rr("sub", RCX, RAX)
            a.mov_rr(RAX, RCX)
        a.alu_rr("add", RAX, RAX)
        a.alu_ri("add", RAX, 1)

    def i_ineg(self, fn, d, x):
        a = self.a
        done = a.new_label("ndone")
        slow = a.new_label("nslow")

        def cold():
            a.label(slow)
            self.ld(RCX, fn, x)
            self.call_rt(fn, "int_neg", [RCX])
            self.st(fn, d, RAX)
            a.jmp(done)
        self.cold.append(cold)
        self.ld(RCX, fn, x)
        a.test_ri8(RCX, 1)
        a.jcc("e", slow)
        a.mov_ri(RAX, 2)
        a.alu_rr("sub", RAX, RCX)
        a.jcc("o", slow)
        self.st(fn, d, RAX)
        a.label(done)

    def icmp_slow(self, fn, x, y_loader, then):
        """Out-of-line int_cmp(x, y); `then()` consumes the flags of `cmp rax, 0`."""
        a = self.a
        slow = a.new_label("cslow")

        def cold():
            a.label(slow)
            self.ld(RAX, fn, x)
            y_loader()
            self.call_rt(fn, "int_cmp", [RAX, RCX])     # returns raw -1 / 0 / 1
            a.alu_ri("cmp", RAX, 0)
            then()
        self.cold.append(cold)
        return slow

    def both_small(self, fn, x, y, slow):
        a = self.a
        rx = self.src(fn, x, RAX)
        ry = self.src(fn, y, RCX)
        a.mov_rr(RDX, rx)
        a.alu_rr("and", RDX, ry)
        a.test_ri8(RDX, 1)
        a.jcc("e", slow)
        return rx, ry

    def i_icmp(self, fn, cc, d, x, y):
        a = self.a
        done = a.new_label("cdone")

        def then():
            a.setcc(self.CCS[cc], RAX)
            self.st(fn, d, RAX)
            a.jmp(done)
        slow = self.icmp_slow(fn, x, lambda: self.ld(RCX, fn, y), then)
        rx, ry = self.both_small(fn, x, y, slow)
        a.alu_rr("cmp", rx, ry)
        r = self.dst(d, RAX)
        a.setcc(self.CCS[cc], r)
        self.fin(fn, d, r)
        a.label(done)

    def i_icmpi(self, fn, cc, d, x, t):
        a = self.a
        done = a.new_label("cdone")

        def then():
            a.setcc(self.CCS[cc], RAX)
            self.st(fn, d, RAX)
            a.jmp(done)
        slow = self.icmp_slow(fn, x, lambda: a.mov_ri(RCX, t), then)
        rx = self.src(fn, x, RAX)
        a.test_ri8(rx, 1)
        a.jcc("e", slow)
        a.alu_ri("cmp", rx, t)
        r = self.dst(d, RAX)
        a.setcc(self.CCS[cc], r)
        self.fin(fn, d, r)
        a.label(done)

    def far_branch(self, cc, lt, lf):
        self.a.jcc(cc, lt)
        self.a.jmp(lf)

    def i_ibr(self, fn, cc, x, y, lt, lf):
        c = self.CCS[cc]
        slow = self.icmp_slow(fn, x, lambda: self.ld(RCX, fn, y), lambda: self.far_branch(c, lt, lf))
        rx, ry = self.both_small(fn, x, y, slow)
        self.a.alu_rr("cmp", rx, ry)
        self.branch(c, lt, lf)

    def i_ibri(self, fn, cc, x, t, lt, lf):
        a = self.a
        c = self.CCS[cc]
        slow = self.icmp_slow(fn, x, lambda: a.mov_ri(RCX, t), lambda: self.far_branch(c, lt, lf))
        rx = self.src(fn, x, RAX)
        a.test_ri8(rx, 1)
        a.jcc("e", slow)
        a.alu_ri("cmp", rx, t)
        self.branch(c, lt, lf)

    # ---- memory ------------------------------------------------------------------------
    def i_load(self, fn, d, base, off):
        rb = self.src(fn, base, RCX)
        r = self.dst(d, RAX)
        self.a.load(r, rb, off)
        self.fin(fn, d, r)

    def i_store(self, fn, base, off, v):
        rb = self.src(fn, base, RCX)
        self.a.store(rb, off, self.src(fn, v, RAX))

    def i_load8(self, fn, d, base, off):
        rb = self.src(fn, base, RCX)
        r = self.dst(d, RAX)
        self.a.load8(r, rb, off)
        self.fin(fn, d, r)

    def i_store8(self, fn, base, off, v):
        rb = self.src(fn, base, RCX)
        self.a.store8(rb, off, self.src(fn, v, RAX))

    def i_load32(self, fn, d, base, off):
        rb = self.src(fn, base, RCX)
        r = self.dst(d, RAX)
        self.a.load32(r, rb, off)
        self.fin(fn, d, r)

    def i_store32(self, fn, base, off, v):
        rb = self.src(fn, base, RCX)
        self.a.store32(rb, off, self.src(fn, v, RAX))

    # ---- reference counting ---------------------------------------------------------------
    def i_retain(self, fn, kind, v):
        a = self.a
        skip = a.new_label("rs")
        r = self.src(fn, v, RAX)
        if kind == "int":
            a.test_ri8(r, 1)
            a.jcc("ne", skip)
        a.load(RCX, r, 0)
        a.test_rr(RCX, RCX)
        a.jcc("s", skip)
        a.alu_ri("add", RCX, 1)
        a.store(r, 0, RCX)
        a.label(skip)

    def i_release(self, fn, kind, v):
        a = self.a
        skip = a.new_label("rl")
        free = a.new_label("rf")
        r = self.src(fn, v, RAX)
        if kind == "int":
            a.test_ri8(r, 1)
            a.jcc("ne", skip)
        a.load(RCX, r, 0)
        a.test_rr(RCX, RCX)
        a.jcc("s", skip)
        a.alu_ri("sub", RCX, 1)
        a.store(r, 0, RCX)
        a.jcc("e", free)
        a.label(skip)

        def cold():
            a.label(free)
            self.ld(RAX, fn, v)
            self.call_rt(fn, "free", [RAX])
            a.jmp(skip)
        self.cold.append(cold)

    # ---- calls & control -------------------------------------------------------------------
    def i_call(self, fn, d, target, args):
        cold = target.startswith("cold:")
        if cold:
            # slow path of an inlined runtime accessor: floats may live in XMM registers across it
            target = target[5:]
            for x, off in zip(self.xmm_used, self.xsave_off):
                self.a.movsd_store(RBP, off, x)
        if target in OS_FUNCS:
            target = "__" + target
        self.emit_call(fn, target, args)
        if cold:
            for x, off in zip(self.xmm_used, self.xsave_off):
                self.a.movsd_load(x, RBP, off)
        if d is not None:
            self.st(fn, d, RAX)

    def i_callind(self, fn, d, fptr, args):
        self.emit_call(fn, None, args, indirect_reg_of=fptr)
        if d is not None:
            self.st(fn, d, RAX)

    def i_label(self, fn, name):
        self.a.label(name)

    def i_jmp(self, fn, name):
        if self.next_label != name:
            self.a.jmp(name)

    def i_br(self, fn, c, lt, lf):
        r = self.src(fn, c, RAX)
        self.a.test_rr(r, r)
        self.branch("ne", lt, lf)

    def i_ret(self, fn, v):
        a = self.a
        if v is not None:
            self.ld(RAX, fn, v)
        for r, off in zip(self.saved, self.save_off):
            a.load(r, RBP, off)
        a.mov_rr(RSP, RBP)
        a.pop(RBP)
        a.ret()

    # Call-stack bookkeeping: only a depth counter (for the 10 000-call limit). The frames of an
    # error trace are reconstructed from the RBP chain + the tables written by finish().
    def i_enter(self, fn, name_sym):
        a = self.a
        over = a.new_label("dep")
        a.alu_ri("add", R15, 1)              # R15: call depth (reserved register)
        a.alu_ri("cmp", R15, MAX_DEPTH)
        a.jcc("g", over)

        def cold():
            a.label(over)
            self.call_rt(fn, "stack_overflow", [])
            a.ud2()
        self.cold.append(cold)

    def i_leave(self, fn):
        self.a.alu_ri("sub", R15, 1)

    def i_site(self, fn, span_sym):
        self.cur_site = span_sym

    def i_fp(self, fn, d):
        self.st(fn, d, RBP)

    # ---- OS layer ----------------------------------------------------------------------------
    def arg(self, reg, i):
        self.a.load(reg, RBP, 16 + 8 * i)

    def stub_begin(self, name):
        a = self.a
        a.label("__" + name)
        a.push(RBP)
        a.mov_rr(RBP, RSP)

    def stub_end(self):
        a = self.a
        a.mov_rr(RSP, RBP)
        a.pop(RBP)
        a.ret()

    def os_layer(self):
        self.img.add_bss("g_depth", 8)
        self.img.add_bss("g_frames", 16 * (MAX_DEPTH + 2))
        self.img.add_bss("g_argp", 8)
        self.img.add_bss("g_scratch", 256)
        if self.target == "linux":
            self.linux_layer()
        else:
            self.windows_layer()

    def linux_layer(self):
        a = self.a
        img = self.img

        def sys(name, nr, nargs, regs=(RDI, RSI, RDX, R10, R8, R9)):
            self.stub_begin(name)
            for i in range(nargs):
                self.arg(regs[i], i)
            a.mov_ri(RAX, nr)
            a.syscall()
            self.stub_end()

        sys("os_write", 1, 3)
        sys("os_read", 0, 3)
        sys("os_close", 3, 1)
        self.stub_begin("os_exit")
        self.arg(RDI, 0)
        a.mov_ri(RAX, 231)
        a.syscall()
        a.ud2()
        self.stub_begin("os_alloc")
        a.mov_ri(RDI, 0)
        self.arg(RSI, 0)
        a.mov_ri(RDX, 3)
        a.mov_ri(R10, 0x22 | 0x4000)   # MAP_PRIVATE | MAP_ANONYMOUS | MAP_NORESERVE
        a.mov_ri(R8, -1)
        a.mov_ri(R9, 0)
        a.mov_ri(RAX, 9)
        a.syscall()
        self.stub_end()
        for name, clock in (("os_time_ns", 1), ("os_wall_ns", 0)):   # CLOCK_MONOTONIC / CLOCK_REALTIME
            self.stub_begin(name)
            a.alu_ri("sub", RSP, 16)
            a.mov_ri(RDI, clock)
            a.mov_rr(RSI, RSP)
            a.mov_ri(RAX, 228)
            a.syscall()
            a.load(RAX, RSP, 0)
            a.mov_ri(RCX, 1000000000)
            a.imul_rr(RAX, RCX)
            a.load(RCX, RSP, 8)
            a.alu_rr("add", RAX, RCX)
            self.stub_end()
        self.stub_begin("os_open")
        self.arg(RDI, 0)
        self.arg(RSI, 1)
        skip = a.new_label("om")
        a.test_rr(RSI, RSI)
        a.jcc("e", skip)
        a.mov_ri(RSI, 0x241)          # O_WRONLY | O_CREAT | O_TRUNC
        a.label(skip)
        a.mov_ri(RDX, 0o644)
        a.mov_ri(RAX, 2)
        a.syscall()
        self.stub_end()
        self.stub_begin("os_file_exists")
        a.alu_ri("sub", RSP, 160)
        self.arg(RDI, 0)
        a.mov_rr(RSI, RSP)
        a.mov_ri(RAX, 4)               # stat
        a.syscall()
        no = a.new_label("fe")
        a.test_rr(RAX, RAX)
        a.jcc("ne", no)
        a.load32(RAX, RSP, 24)         # st_mode
        a.alu_ri("and", RAX, 0xF000)
        a.alu_ri("cmp", RAX, 0x8000)
        a.setcc("e", RAX)
        self.stub_end()
        a.label(no)
        a.mov_ri(RAX, 0)
        self.stub_end()
        self.stub_begin("os_argc")
        a.load_rip(RAX, "g_argp")
        a.load(RAX, RAX, 0)
        self.stub_end()
        self.stub_begin("os_argv")
        a.load_rip(RCX, "g_argp")
        self.arg(RAX, 0)
        a.shift_i("shl", RAX, 3)
        a.alu_rr("add", RCX, RAX)
        a.load(RAX, RCX, 8)
        self.stub_end()
        self.stub_begin("os_cmdline")
        a.mov_ri(RAX, 0)
        self.stub_end()
        self.stub_begin("os_platform")
        a.mov_ri(RAX, 0)
        self.stub_end()
        self.stub_begin("os_getenv")          # Linux reads envp directly (rt/globals.klar)
        a.mov_ri(RAX, 0)
        self.stub_end()
        # os_spawn(argv): fork; the child execve(argv[0], argv, envp), the parent waits -> wait status (or -errno)
        self.stub_begin("os_spawn")
        a.alu_ri("sub", RSP, 16)
        a.mov_ri(RAX, 57)              # fork
        a.syscall()
        done, parent = a.new_label("sd"), a.new_label("sp")
        a.test_rr(RAX, RAX)
        a.jcc("l", done)
        a.jcc("ne", parent)
        self.arg(RSI, 0)
        a.load(RDI, RSI, 0)
        a.load_rip(RCX, "g_argp")
        a.load(RAX, RCX, 0)            # argc
        a.shift_i("shl", RAX, 3)
        a.alu_rr("add", RCX, RAX)
        a.alu_ri("add", RCX, 16)       # envp = &argv[argc + 1]
        a.mov_rr(RDX, RCX)
        a.mov_ri(RAX, 59)              # execve
        a.syscall()
        a.mov_ri(RDI, 127)             # could not run it
        a.mov_ri(RAX, 231)
        a.syscall()
        a.label(parent)
        a.mov_rr(RDI, RAX)
        a.mov_rr(RSI, RSP)
        a.mov_ri(RDX, 0)
        a.mov_ri(R10, 0)
        a.mov_ri(RAX, 61)              # wait4
        a.syscall()
        a.test_rr(RAX, RAX)
        a.jcc("l", done)
        a.load32(RAX, RSP, 0)
        a.label(done)
        self.stub_end()
        self.stub_begin("os_chmod")
        self.arg(RDI, 0)
        self.arg(RSI, 1)
        a.mov_ri(RAX, 90)
        a.syscall()
        self.stub_end()
        self.test_index_stub()
        # entry: remember argc/argv, switch to a 512 MB lazily-committed stack, run, exit
        a.label("_start")
        a.store_rip("g_argp", RSP)
        a.mov_ri(RDI, 0)
        a.mov_ri(RSI, 512 * 1024 * 1024)
        a.mov_ri(RDX, 3)
        a.mov_ri(R10, 0x22 | 0x4000)
        a.mov_ri(R8, -1)
        a.mov_ri(R9, 0)
        a.mov_ri(RAX, 9)
        a.syscall()
        a.mov_ri(RCX, 512 * 1024 * 1024 - 64)
        a.alu_rr("add", RAX, RCX)
        a.mov_rr(RSP, RAX)
        a.mov_rr(RBP, RSP)
        a.mov_ri(R15, 0)                # call depth
        a.call(self.rt["main_entry"])
        a.mov_rr(RDI, RAX)
        a.mov_ri(RAX, 231)
        a.syscall()
        img.entry = "_start"

    def windows_layer(self):
        a = self.a
        self.img.imports = list(WIN_IMPORTS)

        def win_begin(name, extra=0):
            self.stub_begin(name)
            a.push(RBX)                 # RBX is callee-saved in Klar code: [rbp-8]
            a.alu_ri("and", RSP, -16)
            a.alu_ri("sub", RSP, 64 + extra)

        def win_end():
            a.load(RBX, RBP, -8)
            self.stub_end()

        def call(fn):
            a.call_rip("__imp_" + fn)

        def handle_from_fd(reg_fd, std_codes):
            """rcx := handle for fd (0/1/2 -> std handles)."""
            done = a.new_label("h")
            for fd, code in std_codes:
                nxt = a.new_label("hn")
                a.alu_ri("cmp", reg_fd, fd)
                a.jcc("ne", nxt)
                a.mov_ri(RCX, code)
                call("GetStdHandle")
                a.mov_rr(RCX, RAX)
                a.jmp(done)
                a.label(nxt)
            a.mov_rr(RCX, reg_fd)
            a.label(done)

        win_begin("os_write")
        self.arg(RBX, 0)
        handle_from_fd(RBX, [(1, -11), (2, -12)])
        self.arg(RDX, 1)
        self.arg(R8, 2)
        a.lea(R9, RSP, 48)
        a.mov_ri(RAX, 0)
        a.store(RSP, 48, RAX)
        a.store(RSP, 32, RAX)
        call("WriteFile")
        a.load(RAX, RSP, 48)
        win_end()

        win_begin("os_read")
        self.arg(RBX, 0)
        handle_from_fd(RBX, [(0, -10)])
        self.arg(RDX, 1)
        self.arg(R8, 2)
        a.lea(R9, RSP, 48)
        a.mov_ri(RAX, 0)
        a.store(RSP, 48, RAX)
        a.store(RSP, 32, RAX)
        call("ReadFile")
        a.load(RAX, RSP, 48)
        win_end()

        win_begin("os_close")
        self.arg(RCX, 0)
        call("CloseHandle")
        win_end()

        win_begin("os_exit")
        self.arg(RCX, 0)
        call("ExitProcess")
        a.ud2()

        win_begin("os_alloc")
        a.mov_ri(RCX, 0)
        self.arg(RDX, 0)
        a.mov_ri(R8, 0x3000)
        a.mov_ri(R9, 4)
        call("VirtualAlloc")
        win_end()

        win_begin("os_time_ns")
        a.lea(RCX, RSP, 48)
        call("QueryPerformanceCounter")
        a.lea(RCX, RSP, 56)
        call("QueryPerformanceFrequency")
        a.load(RAX, RSP, 48)
        a.mov_ri(RCX, 1000000000)
        a.mul(RCX)
        a.load(RCX, RSP, 56)
        a.div(RCX)
        win_end()

        win_begin("os_wall_ns")                  # FILETIME: 100 ns since 1601-01-01
        a.lea(RCX, RSP, 48)
        call("GetSystemTimeAsFileTime")
        a.load(RAX, RSP, 48)
        a.mov_ri(RCX, 116444736000000000)
        a.alu_rr("sub", RAX, RCX)
        a.mov_ri(RCX, 100)
        a.imul_rr(RAX, RCX)
        win_end()

        win_begin("os_open", 16)
        self.arg(RCX, 0)
        self.arg(RBX, 1)
        wr = a.new_label("ow")
        done = a.new_label("od")
        a.test_rr(RBX, RBX)
        a.jcc("ne", wr)
        a.mov_ri(RDX, 0x80000000)
        a.mov_ri(RAX, 3)               # OPEN_EXISTING
        a.jmp(done)
        a.label(wr)
        a.mov_ri(RDX, 0x40000000)
        a.mov_ri(RAX, 2)               # CREATE_ALWAYS
        a.label(done)
        a.store(RSP, 32, RAX)
        a.mov_ri(R8, 1)
        a.mov_ri(R9, 0)
        a.mov_ri(RAX, 0x80)
        a.store(RSP, 40, RAX)
        a.mov_ri(RAX, 0)
        a.store(RSP, 48, RAX)
        call("CreateFileA")
        win_end()

        win_begin("os_file_exists")
        self.arg(RCX, 0)
        call("GetFileAttributesA")
        no = a.new_label("fx")
        a.mov_ri(RCX, 0xFFFFFFFF)      # the DWORD result lives in eax: zero-extend, then test for -1
        a.alu_rr("and", RAX, RCX)
        a.alu_rr("cmp", RAX, RCX)
        a.jcc("e", no)
        a.alu_ri("and", RAX, 0x10)
        a.alu_ri("cmp", RAX, 0)
        a.setcc("e", RAX)
        win_end()
        a.label(no)
        a.mov_ri(RAX, 0)
        win_end()

        win_begin("os_cmdline")
        call("GetCommandLineA")
        win_end()

        win_begin("os_getenv")
        self.arg(RCX, 0)
        self.arg(RDX, 1)
        self.arg(R8, 2)
        call("GetEnvironmentVariableA")
        a.mov_ri(RCX, 0xFFFFFFFF)
        a.alu_rr("and", RAX, RCX)       # DWORD result
        win_end()
        for name in ("os_argc", "os_argv"):
            self.stub_begin(name)
            a.mov_ri(RAX, 0)
            self.stub_end()
        self.stub_begin("os_platform")
        a.mov_ri(RAX, 1)
        self.stub_end()
        # os_spawn(command line) -> exit code (-1: could not start); STARTUPINFOA at [rsp+80], PROCESS_INFORMATION at
        # [rsp+184], the exit code at [rsp+208]
        win_begin("os_spawn", 160)
        a.mov_ri(RAX, 0)
        for k in range(17):
            a.store(RSP, 80 + 8 * k, RAX)
        a.mov_ri(RAX, 104)
        a.store(RSP, 80, RAX)          # cb
        a.mov_ri(RCX, 0)
        self.arg(RDX, 0)
        a.mov_ri(R8, 0)
        a.mov_ri(R9, 0)
        a.mov_ri(RAX, 1)
        a.store(RSP, 32, RAX)          # inherit handles
        a.mov_ri(RAX, 0)
        a.store(RSP, 40, RAX)
        a.store(RSP, 48, RAX)
        a.store(RSP, 56, RAX)
        a.lea(RAX, RSP, 80)
        a.store(RSP, 64, RAX)
        a.lea(RAX, RSP, 184)
        a.store(RSP, 72, RAX)
        call("CreateProcessA")
        fail = a.new_label("sf")
        a.mov_ri(RCX, 0xFFFFFFFF)
        a.alu_rr("and", RAX, RCX)
        a.jcc("e", fail)
        a.load(RCX, RSP, 184)
        a.mov_ri(RDX, 0xFFFFFFFF)      # INFINITE
        call("WaitForSingleObject")
        a.load(RCX, RSP, 184)
        a.lea(RDX, RSP, 208)
        call("GetExitCodeProcess")
        a.load(RCX, RSP, 184)
        call("CloseHandle")
        a.load(RCX, RSP, 192)
        call("CloseHandle")
        a.load32(RAX, RSP, 208)
        win_end()
        a.label(fail)
        a.mov_ri(RAX, -1)
        win_end()
        self.stub_begin("os_chmod")
        a.mov_ri(RAX, 0)
        self.stub_end()
        self.test_index_stub()

        a.label("_start")
        a.alu_ri("and", RSP, -16)
        a.alu_ri("sub", RSP, 32)
        a.mov_ri(RCX, 65001)
        call("SetConsoleOutputCP")
        a.mov_ri(RAX, 0)                # [rbp] = 0, [rbp+8] = 0: end of the frame chain for traces
        a.store(RSP, 0, RAX)
        a.store(RSP, 8, RAX)
        a.mov_rr(RBP, RSP)
        a.mov_ri(R15, 0)                # call depth
        a.call(self.rt["main_entry"])
        a.mov_rr(RCX, RAX)
        a.alu_ri("and", RSP, -16)
        a.alu_ri("sub", RSP, 32)
        call("ExitProcess")
        self.img.entry = "_start"

    def test_index_stub(self):
        """test_index_arg(): decimal value of the last command-line word (test executables)."""
        a = self.a
        a.label("test_index_arg")
        a.push(RBP)
        a.mov_rr(RBP, RSP)
        if self.target == "linux":
            a.load_rip(RCX, "g_argp")
            a.load(RAX, RCX, 0)             # argc
            a.shift_i("shl", RAX, 3)
            a.alu_rr("add", RCX, RAX)
            a.load(RSI, RCX, 0)             # argv[argc-1]
        else:
            a.alu_ri("and", RSP, -16)
            a.alu_ri("sub", RSP, 32)
            a.call_rip("__imp_GetCommandLineA")
            a.mov_rr(RSI, RAX)
            # move to the last space-separated word
            scan, end, nosp = a.new_label("s"), a.new_label("e"), a.new_label("ns")
            a.mov_rr(RDX, RSI)
            a.label(scan)
            a.load8(RCX, RSI, 0)
            a.test_rr(RCX, RCX)
            a.jcc("e", end)
            a.alu_ri("cmp", RCX, 32)
            a.jcc("ne", nosp)
            a.mov_rr(RDX, RSI)
            a.alu_ri("add", RDX, 1)
            a.label(nosp)
            a.alu_ri("add", RSI, 1)
            a.jmp(scan)
            a.label(end)
            a.mov_rr(RSI, RDX)
        a.mov_ri(RAX, 0)
        loop, done = a.new_label("d"), a.new_label("dd")
        a.label(loop)
        a.load8(RCX, RSI, 0)
        a.alu_ri("sub", RCX, 48)
        a.jcc("l", done)
        a.alu_ri("cmp", RCX, 9)
        a.jcc("g", done)
        a.mov_ri(RDX, 10)
        a.imul_rr(RAX, RDX)
        a.alu_rr("add", RAX, RCX)
        a.alu_ri("add", RSI, 1)
        a.jmp(loop)
        a.label(done)
        a.mov_rr(RSP, RBP)
        a.pop(RBP)
        a.ret()

    def trace_tables(self):
        """g_fn_table = [n][start, end, name]*n and g_site_table = [n][return address, span]*n,
        both sorted by address (code is emitted in order)."""
        import struct
        img = self.img

        def table(name, rows):
            payload = bytearray(struct.pack("<q", len(rows)))
            rel = []
            for row in rows:
                for item in row:
                    if item is None:
                        payload += b"\0" * 8
                    else:
                        rel.append((len(payload), item))
                        payload += b"\0" * 8
            img.add_data(name, payload)
            base = img.data_syms[name]
            for off, sym in rel:
                img.data_abs.append((base + off, sym, 0))
        table("g_fn_table", self.user_fns)
        table("g_site_table", self.call_sites)

    def finish(self):
        self.trace_tables()
        self.img.code = self.a.code
        self.img.code_labels = self.a.labels
        self.img.code_fixups = self.a.resolve_local()
