"""KIR -> AArch64 machine code, plus the Linux (arm64) system-call layer. The counterpart of emit.py.

The Klar calling convention is the same as on x86-64, so frames look the same to the runtime: the caller reserves
an argument area of 8*n bytes (rounded up to 16) at [sp] and branches with BL; the callee pushes FP and LR
(`stp x29, x30, [sp, #-16]!`) and reads argument i at [x29+16+8*i]. [x29] is the caller's frame and [x29+8] the
return address, which is what error traces walk. The result is returned in X0.

Registers: X19–X27 callee-saved and X9–X15 caller-saved for values (regalloc.A64), X28 the call depth (R0006 above
10 000 calls), X0–X8 arguments of system calls and scratch, X16/X17 scratch (X16 is also the assembler's address
register). Floats live in D16–D31 (caller-saved) when the allocator puts them there; D0/D1 are scratch.

sin, cos, ln, exp and pow call the runtime's software implementations (`soft_sin` ... in rt/softmath.klar, as on
x86-64), saving the caller-saved registers that are live around them.
"""
from .a64 import Asm, COND, FP, LR, SP, X16, X17, invert
from .emit import MAX_DEPTH, OS_FUNCS, SOFT, align16, sdiv_magic, sdiv_magic64, udiv_magic, udiv_magic_simple
from .regalloc import A64

X0, X1, X2, X3, X4, X5, X8 = 0, 1, 2, 3, 4, 5, 8
X28 = 28
D0, D1 = 0, 1

CCS = {"eq": "eq", "ne": "ne", "lt": "lt", "le": "le", "gt": "gt", "ge": "ge", "ult": "lo", "ule": "ls",
       "ugt": "hi", "uge": "hs"}
# after FCMP: an unordered result (NaN) makes every comparison false except !=
FCC = {"lt": "mi", "le": "ls", "gt": "gt", "ge": "ge", "eq": "eq", "ne": "ne"}


class A64Emitter:
    def __init__(self, image, target, rt):
        self.img = image
        self.target = target       # "linux-arm64"
        self.rt = rt
        self.a = Asm()
        self.user_fns = []
        self.call_sites = []
        self.user = False
        self.cur_site = None

    # ---- locations ---------------------------------------------------------------------------------------
    def slot(self, fn, v):
        if v < fn.nparams:
            return 16 + 8 * v
        return -8 * (v - fn.nparams + 1)

    def ld(self, reg, fn, v):
        r = self.loc.get(v)
        if r is None:
            self.a.load(reg, FP, self.slot(fn, v))
        else:
            self.a.mov_rr(reg, r)

    def st(self, fn, v, reg):
        r = self.loc.get(v)
        if r is None:
            self.a.store(FP, self.slot(fn, v), reg)
        else:
            self.a.mov_rr(r, reg)

    def src(self, fn, v, scratch):
        r = self.loc.get(v)
        if r is not None:
            return r
        self.a.load(scratch, FP, self.slot(fn, v))
        return scratch

    def dst(self, v, scratch):
        return self.loc.get(v, scratch)

    def fin(self, fn, v, reg):
        if v not in self.loc:
            self.a.store(FP, self.slot(fn, v), reg)

    def sub_sp(self, n):
        if not n:
            return
        if self.a.fits_imm12(n):
            self.a.addsub_imm("sub", SP, SP, n)
        else:
            self.a.mov_ri(X16, n)
            self.a.w(0xCB206000 | (X16 << 16) | (SP << 5) | SP)    # sub sp, sp, x16, uxtx

    def add_sp(self, n):
        if not n:
            return
        if self.a.fits_imm12(n):
            self.a.addsub_imm("add", SP, SP, n)
        else:
            self.a.mov_ri(X16, n)
            self.a.w(0x8B206000 | (X16 << 16) | (SP << 5) | SP)    # add sp, sp, x16, uxtx

    def imm_or_reg(self, imm, scratch):
        """For a compare/add: (True, imm) when it fits an immediate, else (False, scratch holding it)."""
        if self.a.fits_imm12(imm):
            return True, imm
        self.a.mov_ri(scratch, imm)
        return False, scratch

    # ---- functions -----------------------------------------------------------------------------------------
    def function(self, fn):
        from .opt import optimize
        from .regalloc import allocate
        optimize(fn)
        self.loc, self.saved, self.xloc = allocate(fn, A64)
        self.slot_needed = self.xmm_slot_needed(fn)
        a = self.a
        enter = next((ins for ins in fn.code if ins[0] == "enter"), None)
        self.user = enter is not None
        self.cur_site = None
        a.label(fn.name)
        a.stp_pre(FP, LR, SP, -16)
        a.mov_rr(FP, SP)
        base = 8 * max(fn.nregs - fn.nparams, 0)
        self.save_off = [-(base + 8 * (k + 1)) for k in range(len(self.saved))]
        self.scratch_off = -(base + 8 * (len(self.saved) + 1))
        self.xmm_used = sorted(set(self.xloc.values()))
        self.xsave_off = [self.scratch_off - 16 - 8 * k for k in range(len(self.xmm_used))]
        self.call_saves = getattr(fn, "call_saves", {})
        csave = sorted({r for regs in self.call_saves.values() for r in regs})
        first = self.scratch_off - 16 - 8 * len(self.xmm_used)
        self.csave_off = {r: first - 8 * k for k, r in enumerate(csave)}
        # software math calls save every live caller-saved register (the allocator counts them as non-calls)
        soft = any(ins[0] == "fpow" or (ins[0] == "fun" and ins[1] != "sqrt") for ins in fn.code)
        self.caller_used = sorted({r for r in self.loc.values() if r in A64.caller}) if soft else []
        first = first - 8 * len(csave)
        self.allsave_off = {r: first - 8 * k for k, r in enumerate(self.caller_used)}
        self.cur_saves = ()
        frame = align16(base + 8 * (len(self.saved) + 2 + len(self.xmm_used) + len(csave) + len(self.caller_used)))
        self.sub_sp(frame)
        for r, off in zip(self.saved, self.save_off):
            a.store(FP, off, r)
        for p in range(fn.nparams):
            if p in self.loc:
                a.load(self.loc[p], FP, self.slot(fn, p))
        self.cold = []
        code = fn.code
        for k, ins in enumerate(code):
            nxt = code[k + 1] if k + 1 < len(code) else None
            self.next_label = nxt[1] if nxt is not None and nxt[0] == "label" else None
            self.cur_saves = sorted(self.call_saves.get(k, ()))
            n_cold = len(self.cold)
            getattr(self, "i_" + ins[0])(fn, *ins[1:])
            if self.cur_saves:
                for j in range(n_cold, len(self.cold)):
                    self.cold[j] = self.with_saves(self.cold[j], self.cur_saves)
            if self.xloc and ins[0] not in self.XMM_AWARE:
                from .opt import defs
                for d in defs(ins):
                    if d in self.xloc:
                        a.fload(self.xloc[d], FP, self.slot(fn, d))
        a.udf()
        self.next_label = None
        for emit_cold in self.cold:
            emit_cold()
        a.udf()
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
            self.a.store(FP, self.csave_off[r], r)

    def restore_live(self):
        for r in self.cur_saves:
            self.a.load(r, FP, self.csave_off[r])

    def save_floats(self):
        for x, off in zip(self.xmm_used, self.xsave_off):
            self.a.fstore(FP, off, x)

    def restore_floats(self):
        for x, off in zip(self.xmm_used, self.xsave_off):
            self.a.fload(x, FP, off)

    def emit_call(self, fn, target, args, indirect_reg_of=None):
        a = self.a
        self.save_live()
        area = align16(8 * len(args))
        self.sub_sp(area)
        for i, v in enumerate(args):
            a.store(SP, 8 * i, self.src(fn, v, X0))
        if indirect_reg_of is not None:
            self.ld(X17, fn, indirect_reg_of)
            a.blr(X17)
        else:
            a.bl(target)
        self.note_site()
        self.add_sp(area)
        self.restore_live()

    def note_site(self):
        if self.user:
            lab = self.a.new_label("ra")
            self.a.label(lab)
            self.call_sites.append((lab, self.cur_site))

    def call_rt(self, fn, name, regs_values):
        a = self.a
        self.save_floats()
        self.save_live()
        area = align16(8 * len(regs_values))
        self.sub_sp(area)
        for i, r in enumerate(regs_values):
            a.store(SP, 8 * i, r)
        a.bl(self.rt[name])
        self.note_site()
        self.add_sp(area)
        self.restore_live()
        self.restore_floats()

    def soft_call(self, fn, helper, args, d):
        """A call of a software math function on a path the allocator treats as call-free: everything live in a
        caller-saved register is saved around it. Arguments and the result are the bits of doubles."""
        a = self.a
        self.save_floats()
        for r in self.caller_used:
            a.store(FP, self.allsave_off[r], r)
        area = align16(8 * len(args))
        self.sub_sp(area)
        for i, v in enumerate(args):
            a.store(SP, 8 * i, self.bits_of(fn, v, X0))
        a.bl(self.rt[helper])
        self.note_site()
        self.add_sp(area)
        for r in self.caller_used:
            a.load(r, FP, self.allsave_off[r])
        self.restore_floats()
        xd = self.xloc.get(d)
        if xd is not None:
            a.fmov_dx(xd, X0)
            if d in self.slot_needed:
                a.store(FP, self.slot(fn, d), X0)
        else:
            self.st(fn, d, X0)

    def bits_of(self, fn, v, scratch):
        """A GP register holding the bits of v (a float vreg possibly in a D register)."""
        x = self.xloc.get(v)
        if x is not None:
            self.a.fmov_xd(scratch, x)
            return scratch
        return self.src(fn, v, scratch)

    # ---- branches --------------------------------------------------------------------------------------------
    def branch(self, cc, lt, lf):
        a = self.a
        if self.next_label == lf:
            a.bcc(cc, lt)
        elif self.next_label == lt:
            a.bcc(invert(cc), lf)
        else:
            a.bcc(cc, lt)
            a.b(lf)

    # ---- floats in D registers ---------------------------------------------------------------------------------
    XMM_AWARE = {"fbin", "fcmp", "fbr", "i2f", "f2i", "const", "mov", "fun", "fpow"}

    def xmm_slot_needed(self, fn):
        from .opt import uses
        need = set()
        if not self.xloc:
            return need
        for ins in fn.code:
            op = ins[0]
            if op in ("fbin", "fcmp", "fbr", "f2i", "mov", "fun", "fpow"):
                continue
            for u in uses(ins):
                if u in self.xloc:
                    need.add(u)
        return need

    def xsrc(self, fn, v, scratch):
        x = self.xloc.get(v)
        if x is not None:
            return x
        r = self.loc.get(v)
        if r is None:
            self.a.fload(scratch, FP, self.slot(fn, v))
        else:
            self.a.fmov_dx(scratch, r)
        return scratch

    def xfin(self, fn, d, x):
        xd = self.xloc.get(d)
        if xd is not None:
            self.a.fmov_dd(xd, x)
            if d in self.slot_needed:
                self.a.fstore(FP, self.slot(fn, d), xd)
            return
        r = self.loc.get(d)
        if r is None:
            self.a.fstore(FP, self.slot(fn, d), x)
        else:
            self.a.fmov_xd(r, x)

    # ---- instructions -------------------------------------------------------------------------------------------
    def i_const(self, fn, d, imm):
        if d in self.xloc:
            self.a.mov_ri(X0, imm)
            self.a.fmov_dx(self.xloc[d], X0)
            if d in self.slot_needed:
                self.a.store(FP, self.slot(fn, d), X0)
            return
        r = self.dst(d, X0)
        self.a.mov_ri(r, imm)
        self.fin(fn, d, r)

    def i_mov(self, fn, d, s):
        if d == s:
            return
        if d in self.xloc or s in self.xloc:
            if d in self.xloc:
                self.xfin(fn, d, self.xsrc(fn, s, D0))
            elif d in self.loc:
                self.a.fmov_xd(self.loc[d], self.xloc[s])
            else:
                self.a.fstore(FP, self.slot(fn, d), self.xloc[s])
            return
        rd = self.loc.get(d)
        if rd is not None:
            self.ld(rd, fn, s)
        else:
            self.st(fn, d, self.src(fn, s, X0))

    def i_addr(self, fn, d, sym):
        r = self.dst(d, X0)
        self.a.adr_sym(r, sym)
        self.fin(fn, d, r)

    def i_bin(self, fn, op, d, x, y):
        a = self.a
        rx = self.src(fn, x, X0)
        ry = self.src(fn, y, X1)
        r = self.dst(d, X2)
        if op in ("add", "sub", "and", "or", "xor", "sdiv", "udiv", "shl", "shr", "sar"):
            a.op3(op, r, rx, ry)
        elif op == "mul":
            a.mul(r, rx, ry)
        elif op in ("srem", "urem"):
            a.op3("sdiv" if op == "srem" else "udiv", X17, rx, ry)
            a.msub(r, X17, ry, rx)
        elif op == "umulhi":
            a.umulh(r, rx, ry)
        else:
            raise ValueError(op)
        self.fin(fn, d, r)

    def i_bini(self, fn, op, d, x, imm):
        a = self.a
        rx = self.src(fn, x, X0)
        r = self.dst(d, X0)
        if op in ("shl", "shr", "sar"):
            a.shift_i(op, r, rx, imm)
        elif op in ("add", "sub") and a.fits_imm12(imm):
            a.addsub_imm(op, r, rx, imm)
        else:
            a.mov_ri(X1, imm)
            if op == "mul":
                a.mul(r, rx, X1)
            else:
                a.op3(op, r, rx, X1)
        self.fin(fn, d, r)

    def i_bink(self, fn, op, d, x, c):
        """Division / remainder by a positive constant: multiply by the rounded reciprocal."""
        a = self.a
        self.ld(X1, fn, x)                          # X1 = x
        if op in ("sdiv", "srem"):
            if c & (c - 1) == 0:
                k = c.bit_length() - 1
                a.mov_rr(X0, X1)
                if k:
                    a.shift_i("sar", X0, X0, 63)
                    a.shift_i("shr", X0, X0, 64 - k)
                    a.op3("add", X0, X0, X1)
                    a.shift_i("sar", X0, X0, k)
            else:
                m, s = sdiv_magic64(c)
                a.mov_ri(X0, m)
                a.smulh(X2, X0, X1)
                if m < 0:
                    a.op3("add", X2, X2, X1)
                if s:
                    a.shift_i("sar", X2, X2, s)
                a.shift_i("shr", X0, X2, 63)
                a.op3("add", X0, X0, X2)
        else:
            if c & (c - 1) == 0:
                k = c.bit_length() - 1
                if op == "udiv":
                    a.shift_i("shr", X1, X1, k)
                else:
                    a.mov_ri(X0, c - 1)
                    a.op3("and", X1, X1, X0)
                self.st(fn, d, X1)
                return
            simple = udiv_magic_simple(c)
            if simple:
                m, s = simple
                a.mov_ri(X0, m)
                a.umulh(X0, X0, X1)
                if s:
                    a.shift_i("shr", X0, X0, s)
            else:
                m, l = udiv_magic(c)
                a.mov_ri(X0, m)
                a.umulh(X2, X0, X1)                 # t
                a.op3("sub", X0, X1, X2)
                a.shift_i("shr", X0, X0, 1)
                a.op3("add", X0, X0, X2)
                a.shift_i("shr", X0, X0, l - 1)
        if op in ("sdiv", "udiv"):
            self.st(fn, d, X0)
            return
        a.mov_ri(X2, c)
        a.msub(X1, X0, X2, X1)                      # x - q*c
        self.st(fn, d, X1)

    def i_cmp(self, fn, cc, d, x, y):
        a = self.a
        a.cmp_rr(self.src(fn, x, X0), self.src(fn, y, X1))
        r = self.dst(d, X0)
        a.cset(r, CCS[cc])
        self.fin(fn, d, r)

    def cmp_imm(self, rx, imm):
        ok, v = self.imm_or_reg(imm, X17)
        if ok:
            self.a.cmp_ri(rx, v)
        else:
            self.a.cmp_rr(rx, v)

    def i_cmpi(self, fn, cc, d, x, imm):
        self.cmp_imm(self.src(fn, x, X0), imm)
        r = self.dst(d, X0)
        self.a.cset(r, CCS[cc])
        self.fin(fn, d, r)

    def i_brc(self, fn, cc, x, y, lt, lf):
        self.a.cmp_rr(self.src(fn, x, X0), self.src(fn, y, X1))
        self.branch(CCS[cc], lt, lf)

    def i_brci(self, fn, cc, x, imm, lt, lf):
        self.cmp_imm(self.src(fn, x, X0), imm)
        self.branch(CCS[cc], lt, lf)

    def i_brti(self, fn, cc, x, imm, lt, lf):
        rx = self.src(fn, x, X0)
        self.a.mov_ri(X17, imm)
        self.a.op3("ands", 31, rx, X17)
        self.branch("ne", lt, lf)

    def i_fbin(self, fn, op, d, x, y):
        xa = self.xsrc(fn, x, D0)
        xb = self.xsrc(fn, y, D1)
        t = self.xloc.get(d, D0)
        self.a.fop(op, t, xa, xb)
        self.xfin(fn, d, t)

    def i_fcmp(self, fn, cc, d, x, y):
        self.a.fcmp(self.xsrc(fn, x, D0), self.xsrc(fn, y, D1))
        self.a.cset(X0, FCC[cc])
        self.st(fn, d, X0)

    def i_fbr(self, fn, cc, x, y, lt, lf):
        self.a.fcmp(self.xsrc(fn, x, D0), self.xsrc(fn, y, D1))
        self.branch(FCC[cc], lt, lf)

    def i_i2f(self, fn, d, x):
        t = self.xloc.get(d, D0)
        self.a.scvtf(t, self.src(fn, x, X0))
        self.xfin(fn, d, t)

    def i_f2i(self, fn, d, x):
        xa = self.xsrc(fn, x, D0)
        r = self.dst(d, X0)
        self.a.fcvtzs(r, xa)
        self.fin(fn, d, r)

    def i_fun(self, fn, op, d, x):
        if op == "sqrt":
            t = self.xloc.get(d, D0)
            self.a.fsqrt(t, self.xsrc(fn, x, D1))
            self.xfin(fn, d, t)
            return
        self.soft_call(fn, SOFT[op], [x], d)

    def i_fpow(self, fn, d, x, y):
        self.soft_call(fn, "soft_pow", [x, y], d)

    # ---- tagged Int fast paths ----------------------------------------------------------------------------------
    def int_slow(self, fn, op, d, x, y_loader, done):
        slow = self.a.new_label("islow")

        def cold():
            a = self.a
            a.label(slow)
            self.ld(X0, fn, x)
            y_loader()
            self.call_rt(fn, "int_" + op, [X0, X1])
            self.st(fn, d, X0)
            a.b(done)
        self.cold.append(cold)
        return slow

    def div_check(self, fn, span, divisor_reg):
        a = self.a
        bad = a.new_label("dz")
        a.cmp_ri(divisor_reg, 1)                 # tagged zero == 1
        a.bcc("eq", bad)

        def cold():
            a.label(bad)
            if span:
                a.adr_sym(X0, span)
            else:
                a.mov_ri(X0, 0)
            self.call_rt(fn, "div_zero", [X0])
            a.udf()
        self.cold.append(cold)

    def mul_overflow_check(self, slow):
        """X2 = X0 * X1 (64-bit); jump to `slow` when the full product does not fit."""
        a = self.a
        a.mul(X2, X0, X1)
        a.smulh(X3, X0, X1)
        a.w(0xEB80FC7F | (X2 << 16))             # cmp x3, x2, asr #63
        a.bcc("ne", slow)

    def i_iop(self, fn, op, d, x, y, span=None):
        a = self.a
        done = a.new_label("idone")
        slow = self.int_slow(fn, op, d, x, lambda: self.ld(X1, fn, y), done)
        self.ld(X0, fn, x)
        self.ld(X1, fn, y)
        if op in ("div", "mod"):
            self.div_check(fn, span, X1)
        a.op3("and", X2, X0, X1)
        a.tst1(X2)
        a.bcc("eq", slow)
        if op in ("add", "sub"):
            a.addsub_imm("sub", X1, X1, 1)
            a.op3("adds" if op == "add" else "subs", X0, X0, X1)
            a.bcc("vs", slow)
        elif op == "mul":
            a.shift_i("sar", X0, X0, 1)
            a.addsub_imm("sub", X1, X1, 1)
            self.mul_overflow_check(slow)
            a.addsub_imm("add", X0, X2, 1)
        elif op in ("div", "mod"):
            a.shift_i("sar", X0, X0, 1)
            a.shift_i("sar", X1, X1, 1)
            a.op3("sdiv", X2, X0, X1)
            if op == "mod":
                a.msub(X2, X2, X1, X0)
            a.op3("adds", X0, X2, X2)
            a.bcc("vs", slow)
            a.addsub_imm("add", X0, X0, 1)
        self.st(fn, d, X0)
        a.label(done)

    def i_iopi(self, fn, op, d, x, t, span=None):
        """Tagged Int op with the constant small Int t (already tagged: 2c+1)."""
        a = self.a
        done = a.new_label("idone")
        slow = self.int_slow(fn, op, d, x, lambda: a.mov_ri(X1, t), done)
        rx = self.src(fn, x, X0)
        a.tst1(rx)
        a.bcc("eq", slow)
        if op in ("add", "sub"):
            r = self.loc.get(d)
            if r is None or r == self.loc.get(x):
                r = X0
            if a.fits_imm12(t - 1):
                a.addsub_imm("adds" if op == "add" else "subs", r, rx, t - 1)
            else:
                a.mov_ri(X17, t - 1)
                a.op3("adds" if op == "add" else "subs", r, rx, X17)
            a.bcc("vs", slow)          # (the slow path recomputes from x, which is untouched)
            self.fin(fn, d, r) if r != X0 else self.st(fn, d, X0)
            a.label(done)
            return
        if op == "mul":
            a.shift_i("sar", X0, rx, 1)
            a.mov_ri(X1, t - 1)
            self.mul_overflow_check(slow)
            a.addsub_imm("add", X0, X2, 1)
        elif op in ("div", "mod") and abs(t >> 1) >= 2:
            a.mov_rr(X0, rx)
            self.const_divmod(op, t >> 1)
        elif op in ("div", "mod"):
            a.shift_i("sar", X0, rx, 1)
            a.mov_ri(X1, t >> 1)
            a.op3("sdiv", X2, X0, X1)
            if op == "mod":
                a.msub(X2, X2, X1, X0)
            a.op3("adds", X0, X2, X2)
            a.bcc("vs", slow)
            a.addsub_imm("add", X0, X0, 1)
        self.st(fn, d, X0)
        a.label(done)

    def const_divmod(self, op, c):
        """X0 = tagged small Int -> tagged (X0 / c) or (X0 % c), truncating; |c| >= 2 (reciprocal multiply)."""
        a = self.a
        a.shift_i("sar", X1, X0, 1)               # X1 = a
        ac = abs(c)
        if ac & (ac - 1) == 0:
            k = ac.bit_length() - 1
            a.shift_i("sar", X0, X1, 63)
            a.shift_i("shr", X0, X0, 64 - k)
            a.op3("add", X0, X0, X1)
            a.shift_i("sar", X0, X0, k)
        else:
            m, s = sdiv_magic(ac)
            a.mov_ri(X2, m)
            a.smulh(X3, X1, X2)
            if s:
                a.shift_i("sar", X3, X3, s)
            a.shift_i("shr", X0, X1, 63)
            a.op3("add", X0, X0, X3)
        if c < 0:
            a.neg(X0, X0)
        if op == "mod":
            a.mov_ri(X2, c)
            a.msub(X0, X0, X2, X1)               # a - q*c
        a.op3("add", X0, X0, X0)
        a.addsub_imm("add", X0, X0, 1)

    def i_ineg(self, fn, d, x):
        a = self.a
        done = a.new_label("ndone")
        slow = a.new_label("nslow")

        def cold():
            a.label(slow)
            self.ld(X1, fn, x)
            self.call_rt(fn, "int_neg", [X1])
            self.st(fn, d, X0)
            a.b(done)
        self.cold.append(cold)
        self.ld(X1, fn, x)
        a.tst1(X1)
        a.bcc("eq", slow)
        a.mov_ri(X0, 2)
        a.op3("subs", X0, X0, X1)
        a.bcc("vs", slow)
        self.st(fn, d, X0)
        a.label(done)

    def icmp_slow(self, fn, x, y_loader, then):
        a = self.a
        slow = a.new_label("cslow")

        def cold():
            a.label(slow)
            self.ld(X0, fn, x)
            y_loader()
            self.call_rt(fn, "int_cmp", [X0, X1])        # raw -1 / 0 / 1
            a.cmp_ri(X0, 0)
            then()
        self.cold.append(cold)
        return slow

    def both_small(self, fn, x, y, slow):
        a = self.a
        rx = self.src(fn, x, X0)
        ry = self.src(fn, y, X1)
        a.op3("and", X2, rx, ry)
        a.tst1(X2)
        a.bcc("eq", slow)
        return rx, ry

    def i_icmp(self, fn, cc, d, x, y):
        a = self.a
        done = a.new_label("cdone")

        def then():
            a.cset(X0, CCS[cc])
            self.st(fn, d, X0)
            a.b(done)
        slow = self.icmp_slow(fn, x, lambda: self.ld(X1, fn, y), then)
        rx, ry = self.both_small(fn, x, y, slow)
        a.cmp_rr(rx, ry)
        r = self.dst(d, X0)
        a.cset(r, CCS[cc])
        self.fin(fn, d, r)
        a.label(done)

    def i_icmpi(self, fn, cc, d, x, t):
        a = self.a
        done = a.new_label("cdone")

        def then():
            a.cset(X0, CCS[cc])
            self.st(fn, d, X0)
            a.b(done)
        slow = self.icmp_slow(fn, x, lambda: a.mov_ri(X1, t), then)
        rx = self.src(fn, x, X0)
        a.tst1(rx)
        a.bcc("eq", slow)
        self.cmp_imm(rx, t)
        r = self.dst(d, X0)
        a.cset(r, CCS[cc])
        self.fin(fn, d, r)
        a.label(done)

    def far_branch(self, cc, lt, lf):
        self.a.bcc(cc, lt)
        self.a.b(lf)

    def i_ibr(self, fn, cc, x, y, lt, lf):
        c = CCS[cc]
        slow = self.icmp_slow(fn, x, lambda: self.ld(X1, fn, y), lambda: self.far_branch(c, lt, lf))
        rx, ry = self.both_small(fn, x, y, slow)
        self.a.cmp_rr(rx, ry)
        self.branch(c, lt, lf)

    def i_ibri(self, fn, cc, x, t, lt, lf):
        a = self.a
        c = CCS[cc]
        slow = self.icmp_slow(fn, x, lambda: a.mov_ri(X1, t), lambda: self.far_branch(c, lt, lf))
        rx = self.src(fn, x, X0)
        a.tst1(rx)
        a.bcc("eq", slow)
        self.cmp_imm(rx, t)
        self.branch(c, lt, lf)

    # ---- memory -------------------------------------------------------------------------------------------------
    def i_load(self, fn, d, base, off):
        rb = self.src(fn, base, X1)
        r = self.dst(d, X0)
        self.a.mem("ldr", r, rb, off)
        self.fin(fn, d, r)

    def i_store(self, fn, base, off, v):
        rb = self.src(fn, base, X1)
        self.a.mem("str", self.src(fn, v, X0), rb, off)

    def i_load8(self, fn, d, base, off):
        rb = self.src(fn, base, X1)
        r = self.dst(d, X0)
        self.a.mem("ldrb", r, rb, off)
        self.fin(fn, d, r)

    def i_store8(self, fn, base, off, v):
        rb = self.src(fn, base, X1)
        self.a.mem("strb", self.src(fn, v, X0), rb, off)

    def i_load32(self, fn, d, base, off):
        rb = self.src(fn, base, X1)
        r = self.dst(d, X0)
        self.a.mem("ldrw", r, rb, off)
        self.fin(fn, d, r)

    def i_store32(self, fn, base, off, v):
        rb = self.src(fn, base, X1)
        self.a.mem("strw", self.src(fn, v, X0), rb, off)

    # ---- reference counting -------------------------------------------------------------------------------------
    def i_retain(self, fn, kind, v):
        a = self.a
        skip = a.new_label("rs")
        r = self.src(fn, v, X0)
        if kind == "int":
            a.tst1(r)
            a.bcc("ne", skip)
        a.load(X1, r, 0)
        a.cmp_ri(X1, 0)
        a.bcc("lt", skip)                         # (negative counts: static objects)
        a.addsub_imm("add", X1, X1, 1)
        a.store(r, 0, X1)
        a.label(skip)

    def i_release(self, fn, kind, v):
        a = self.a
        skip = a.new_label("rl")
        free = a.new_label("rf")
        r = self.src(fn, v, X0)
        if kind == "int":
            a.tst1(r)
            a.bcc("ne", skip)
        a.load(X1, r, 0)
        a.cmp_ri(X1, 0)
        a.bcc("lt", skip)
        a.addsub_imm("subs", X1, X1, 1)
        a.store(r, 0, X1)
        a.bcc("eq", free)
        a.label(skip)

        def cold():
            a.label(free)
            self.ld(X0, fn, v)
            self.call_rt(fn, "free", [X0])
            a.b(skip)
        self.cold.append(cold)

    # ---- calls & control ----------------------------------------------------------------------------------------
    def i_call(self, fn, d, target, args):
        cold = target.startswith("cold:")
        if cold:
            target = target[5:]
            self.save_floats()
        if target in OS_FUNCS:
            target = "__" + target
        self.emit_call(fn, target, args)
        if cold:
            self.restore_floats()
        if d is not None:
            self.st(fn, d, X0)

    def i_callind(self, fn, d, fptr, args):
        self.emit_call(fn, None, args, indirect_reg_of=fptr)
        if d is not None:
            self.st(fn, d, X0)

    def i_label(self, fn, name):
        self.a.label(name)

    def i_jmp(self, fn, name):
        if self.next_label != name:
            self.a.b(name)

    def i_br(self, fn, c, lt, lf):
        self.a.cmp_ri(self.src(fn, c, X0), 0)
        self.branch("ne", lt, lf)

    def i_ret(self, fn, v):
        a = self.a
        if v is not None:
            self.ld(X0, fn, v)
        for r, off in zip(self.saved, self.save_off):
            a.load(r, FP, off)
        a.mov_rr(SP, FP)
        a.ldp_post(FP, LR, SP, 16)
        a.ret()

    def i_enter(self, fn, name_sym):
        a = self.a
        over = a.new_label("dep")
        a.addsub_imm("add", X28, X28, 1)          # X28: call depth (reserved register)
        a.mov_ri(X17, MAX_DEPTH)
        a.cmp_rr(X28, X17)
        a.bcc("gt", over)

        def cold():
            a.label(over)
            self.call_rt(fn, "stack_overflow", [])
            a.udf()
        self.cold.append(cold)

    def i_leave(self, fn):
        self.a.addsub_imm("sub", X28, X28, 1)

    def i_site(self, fn, span_sym):
        self.cur_site = span_sym

    def i_fp(self, fn, d):
        self.st(fn, d, FP)

    # ---- the Linux (arm64) system-call layer -------------------------------------------------------------------
    def arg(self, reg, i):
        self.a.load(reg, FP, 16 + 8 * i)

    def stub_begin(self, name):
        a = self.a
        a.label("__" + name)
        a.stp_pre(FP, LR, SP, -16)
        a.mov_rr(FP, SP)

    def stub_end(self):
        a = self.a
        a.mov_rr(SP, FP)
        a.ldp_post(FP, LR, SP, 16)
        a.ret()

    def syscall(self, nr):
        self.a.mov_ri(X8, nr)
        self.a.svc()

    def os_layer(self):
        self.img.add_bss("g_depth", 8)
        self.img.add_bss("g_frames", 16 * (MAX_DEPTH + 2))
        self.img.add_bss("g_argp", 8)
        self.img.add_bss("g_scratch", 256)
        a = self.a
        AT_FDCWD = -100

        def sys(name, nr, nargs):
            self.stub_begin(name)
            for i in range(nargs):
                self.arg(i, i)
            self.syscall(nr)
            self.stub_end()

        sys("os_write", 64, 3)
        sys("os_read", 63, 3)
        sys("os_close", 57, 1)
        self.stub_begin("os_exit")
        self.arg(X0, 0)
        self.syscall(94)                       # exit_group
        a.udf()
        self.stub_begin("os_alloc")
        a.mov_ri(X0, 0)
        self.arg(X1, 0)
        a.mov_ri(X2, 3)
        a.mov_ri(X3, 0x22 | 0x4000)            # MAP_PRIVATE | MAP_ANONYMOUS | MAP_NORESERVE
        a.mov_ri(X4, -1)
        a.mov_ri(X5, 0)
        self.syscall(222)                      # mmap
        self.stub_end()
        for name, clock in (("os_time_ns", 1), ("os_wall_ns", 0)):
            self.stub_begin(name)
            a.addsub_imm("sub", SP, SP, 16)
            a.mov_ri(X0, clock)
            a.mov_rr(X1, SP)
            self.syscall(113)                  # clock_gettime
            a.load(X0, SP, 0)
            a.mov_ri(X1, 1000000000)
            a.mul(X0, X0, X1)
            a.load(X1, SP, 8)
            a.op3("add", X0, X0, X1)
            self.stub_end()
        self.stub_begin("os_open")
        self.arg(X1, 0)
        self.arg(X2, 1)
        skip = a.new_label("om")
        a.cbz(X2, skip)
        a.mov_ri(X2, 0x241)                    # O_WRONLY | O_CREAT | O_TRUNC
        a.label(skip)
        a.mov_ri(X3, 0o644)
        a.mov_ri(X0, AT_FDCWD)
        self.syscall(56)                       # openat
        self.stub_end()
        self.stub_begin("os_file_exists")
        a.addsub_imm("sub", SP, SP, 144)
        a.mov_ri(X0, AT_FDCWD)
        self.arg(X1, 0)
        a.mov_rr(X2, SP)
        a.mov_ri(X3, 0)
        self.syscall(79)                       # newfstatat
        no = a.new_label("fe")
        a.cbnz(X0, no)
        a.mem("ldrw", X0, SP, 16)              # st_mode
        a.mov_ri(X1, 0xF000)
        a.op3("and", X0, X0, X1)
        a.mov_ri(X1, 0x8000)
        a.cmp_rr(X0, X1)
        a.cset(X0, "eq")
        self.stub_end()
        a.label(no)
        a.mov_ri(X0, 0)
        self.stub_end()
        self.stub_begin("os_argc")
        a.adr_sym(X0, "g_argp")
        a.load(X0, X0, 0)
        a.load(X0, X0, 0)
        self.stub_end()
        self.stub_begin("os_argv")
        a.adr_sym(X1, "g_argp")
        a.load(X1, X1, 0)
        self.arg(X0, 0)
        a.shift_i("shl", X0, X0, 3)
        a.op3("add", X1, X1, X0)
        a.load(X0, X1, 8)
        self.stub_end()
        for name in ("os_cmdline", "os_platform", "os_getenv"):
            self.stub_begin(name)
            a.mov_ri(X0, 0)
            self.stub_end()
        # os_spawn(argv): clone (like fork); the child execve(argv[0], argv, envp), the parent waits
        self.stub_begin("os_spawn")
        a.addsub_imm("sub", SP, SP, 16)
        a.mov_ri(X0, 17)                       # SIGCHLD
        for r in (X1, X2, X3, X4):
            a.mov_ri(r, 0)
        self.syscall(220)                      # clone
        done, parent = a.new_label("sd"), a.new_label("sp")
        a.cmp_ri(X0, 0)
        a.bcc("lt", done)
        a.bcc("ne", parent)
        self.arg(X1, 0)
        a.load(X0, X1, 0)
        a.adr_sym(X3, "g_argp")
        a.load(X3, X3, 0)
        a.load(X2, X3, 0)                      # argc
        a.shift_i("shl", X2, X2, 3)
        a.op3("add", X2, X3, X2)
        a.addsub_imm("add", X2, X2, 16)        # envp = &argv[argc + 1]
        self.syscall(221)                      # execve
        a.mov_ri(X0, 127)
        self.syscall(94)
        a.label(parent)
        a.mov_rr(X1, SP)
        a.mov_ri(X2, 0)
        a.mov_ri(X3, 0)
        self.syscall(260)                      # wait4(pid, &status, 0, 0)
        a.cmp_ri(X0, 0)
        a.bcc("lt", done)
        a.mem("ldrw", X0, SP, 0)
        a.label(done)
        self.stub_end()
        self.stub_begin("os_chmod")
        a.mov_ri(X0, AT_FDCWD)
        self.arg(X1, 0)
        self.arg(X2, 1)
        a.mov_ri(X3, 0)
        self.syscall(53)                       # fchmodat
        self.stub_end()
        # worker processes for List.par_map (rt/par.klar)
        self.stub_begin("os_fork")
        a.mov_ri(X0, 17)                       # clone(SIGCHLD, 0, 0, 0, 0): fork
        for r in (X1, X2, X3, X4):
            a.mov_ri(r, 0)
        self.syscall(220)
        self.stub_end()
        self.stub_begin("os_pipe")
        self.arg(X0, 0)
        a.mov_ri(X1, 0)
        self.syscall(59)                       # pipe2
        self.stub_end()
        self.stub_begin("os_wait")             # wait4(pid, &status, 0, 0) -> wait status (or -errno)
        a.addsub_imm("sub", SP, SP, 16)
        self.arg(X0, 0)
        a.mov_rr(X1, SP)
        a.mov_ri(X2, 0)
        a.mov_ri(X3, 0)
        self.syscall(260)
        done = a.new_label("wd")
        a.cmp_ri(X0, 0)
        a.bcc("lt", done)
        a.mem("ldrw", X0, SP, 0)
        a.label(done)
        self.stub_end()
        sys("os_kill", 129, 2)
        self.stub_begin("os_cpu_mask")         # sched_getaffinity(0, n, buf) -> bytes written (or -errno)
        a.mov_ri(X0, 0)
        self.arg(X1, 1)
        self.arg(X2, 0)
        self.syscall(123)
        self.stub_end()
        # directories (list_dir / is_dir)
        self.stub_begin("os_is_dir")
        a.addsub_imm("sub", SP, SP, 144)
        a.mov_ri(X0, AT_FDCWD)
        self.arg(X1, 0)
        a.mov_rr(X2, SP)
        a.mov_ri(X3, 0)
        self.syscall(79)                       # newfstatat
        no = a.new_label("dn")
        a.cbnz(X0, no)
        a.mem("ldrw", X0, SP, 16)              # st_mode
        a.mov_ri(X1, 0xF000)
        a.op3("and", X0, X0, X1)
        a.mov_ri(X1, 0x4000)
        a.cmp_rr(X0, X1)
        a.cset(X0, "eq")
        self.stub_end()
        a.label(no)
        a.mov_ri(X0, 0)
        self.stub_end()
        sys("os_getdents", 61, 3)
        self.stub_begin("os_mkdir")            # mkdirat(AT_FDCWD, path, 0755) -> 0 or -errno
        a.mov_ri(X0, AT_FDCWD)
        self.arg(X1, 0)
        a.mov_ri(X2, 0o755)
        self.syscall(34)
        self.stub_end()
        # programs with captured output (run_capture)
        self.stub_begin("os_dup2")             # dup3(old, new, 0)
        self.arg(X0, 0)
        self.arg(X1, 1)
        a.mov_ri(X2, 0)
        self.syscall(24)
        self.stub_end()
        sys("os_chdir", 49, 1)
        sys("os_execve", 221, 3)
        self.stub_begin("os_unlink")           # unlinkat(AT_FDCWD, path, 0)
        a.mov_ri(X0, AT_FDCWD)
        self.arg(X1, 0)
        a.mov_ri(X2, 0)
        self.syscall(35)
        self.stub_end()
        sys("os_getcwd", 17, 2)                # -> length with the final NUL
        self.stub_begin("os_readlink")         # readlinkat(AT_FDCWD, path, buf, n)
        a.mov_ri(X0, AT_FDCWD)
        self.arg(X1, 0)
        self.arg(X2, 1)
        self.arg(X3, 2)
        self.syscall(78)
        self.stub_end()
        self.stub_begin("os_poll")             # ppoll(fds, n, NULL, NULL, 0)
        self.arg(X0, 0)
        self.arg(X1, 1)
        for r in (X2, X3, X4):
            a.mov_ri(r, 0)
        self.syscall(73)
        self.stub_end()
        for name in ("os_find_first", "os_find_next", "os_find_close", "os_spawn_std"):     # (Windows)
            self.stub_begin(name)
            a.mov_ri(X0, -1)
            self.stub_end()
        self.stub_begin("os_setjmp")           # (Windows: property runs without fork)
        a.mov_ri(X0, -1)
        self.stub_end()
        self.stub_begin("os_longjmp")
        a.udf()
        self.test_index_stub()
        # entry: remember argc/argv, switch to a 512 MB lazily-committed stack, run, exit
        a.label("_start")
        a.mov_rr(X0, SP)
        a.adr_sym(X1, "g_argp")
        a.store(X1, 0, X0)
        a.mov_ri(X0, 0)
        a.mov_ri(X1, 512 * 1024 * 1024)
        a.mov_ri(X2, 3)
        a.mov_ri(X3, 0x22 | 0x4000)
        a.mov_ri(X4, -1)
        a.mov_ri(X5, 0)
        self.syscall(222)
        a.mov_ri(X1, 512 * 1024 * 1024 - 64)
        a.op3("add", X0, X0, X1)
        a.mov_rr(SP, X0)
        a.mov_rr(FP, SP)
        a.mov_ri(X28, 0)
        a.bl(self.rt["main_entry"])
        self.syscall(94)
        self.img.entry = "_start"

    def test_index_stub(self):
        """test_index_arg(): decimal value of the last command-line word (test executables)."""
        a = self.a
        a.label("test_index_arg")
        a.stp_pre(FP, LR, SP, -16)
        a.mov_rr(FP, SP)
        a.adr_sym(X1, "g_argp")
        a.load(X1, X1, 0)
        a.load(X0, X1, 0)                      # argc
        a.shift_i("shl", X0, X0, 3)
        a.op3("add", X1, X1, X0)
        a.load(X1, X1, 0)                      # argv[argc-1]
        a.mov_ri(X0, 0)
        loop, done = a.new_label("d"), a.new_label("dd")
        a.label(loop)
        a.mem("ldrb", X2, X1, 0)
        a.addsub_imm("subs", X2, X2, 48)
        a.bcc("lt", done)
        a.cmp_ri(X2, 9)
        a.bcc("gt", done)
        a.mov_ri(X3, 10)
        a.mul(X0, X0, X3)
        a.op3("add", X0, X0, X2)
        a.addsub_imm("add", X1, X1, 1)
        a.b(loop)
        a.label(done)
        self.stub_end()

    def trace_tables(self):
        import struct
        img = self.img

        def table(name, rows):
            payload = bytearray(struct.pack("<q", len(rows)))
            rel = []
            for row in rows:
                for item in row:
                    if item is not None:
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
        self.img.machine = "aarch64"


__all__ = ["A64Emitter", "COND"]
