"""A small AArch64 (ARM64) assembler: encodes the instructions the Klar backend needs.

Registers are numbers: X0–X30 general purpose, 31 is SP or XZR depending on the instruction (as in the
architecture), D0–D31 the double-precision registers. Code refers to data only PC-relatively (ADRP + ADD), so it
works at any load address. Local branches are resolved by `resolve_local`; references to data symbols stay as
fixups for the linker: ("page", target) on an ADRP and ("lo12", target) on the ADD that follows it.
"""
import struct

X16, X17 = 16, 17          # IP0 / IP1: the assembler's and the emitter's scratch registers
FP, LR, SP, XZR = 29, 30, 31, 31

COND = {"eq": 0, "ne": 1, "hs": 2, "lo": 3, "mi": 4, "pl": 5, "vs": 6, "vc": 7, "hi": 8, "ls": 9, "ge": 10,
        "lt": 11, "gt": 12, "le": 13, "al": 14}


def invert(cc):
    return {v: k for k, v in COND.items()}[COND[cc] ^ 1]


class Asm:
    def __init__(self):
        self.code = bytearray()
        self.labels = {}
        self.branches = []         # (pos, label, kind): kind "b26" | "b19" — resolved locally
        self.fixups = []           # (pos, target, kind): "page" | "lo12" — for the linker
        self._n = 0

    # ---- labels ---------------------------------------------------------------------------------------
    def new_label(self, hint="L"):
        self._n += 1
        return f".{hint}{self._n}"

    def label(self, name):
        if name in self.labels:
            raise ValueError(f"duplicate label {name}")
        self.labels[name] = len(self.code)

    def here(self):
        return len(self.code)

    def w(self, word):
        self.code += struct.pack("<I", word & 0xFFFFFFFF)

    def resolve_local(self):
        """Patches the branches to local labels; returns the fixups left for the linker (targets outside the
        code: data symbols, and labels of other code when `labels` does not have them)."""
        out = []
        for pos, target, kind in self.branches:
            if target not in self.labels:
                raise KeyError(f"unresolved code label {target}")
            delta = (self.labels[target] - pos) >> 2
            word, = struct.unpack_from("<I", self.code, pos)
            if kind == "b26":
                if not -(1 << 25) <= delta < (1 << 25):
                    raise ValueError("branch out of range")
                word |= delta & 0x3FFFFFF
            else:
                if not -(1 << 18) <= delta < (1 << 18):
                    raise ValueError(f"conditional branch to {target} out of range")
                word |= (delta & 0x7FFFF) << 5
            struct.pack_into("<I", self.code, pos, word)
        for pos, target, kind in self.fixups:
            out.append((pos, target, kind))
        return out

    # ---- moves ----------------------------------------------------------------------------------------
    def mov_rr(self, rd, rn):
        if rd == rn:
            return
        if rd == SP or rn == SP:
            self.w(0x91000000 | (rn << 5) | rd)                 # add rd, rn, #0
        else:
            self.w(0xAA0003E0 | (rn << 16) | rd)                # orr rd, xzr, rn

    def mov_ri(self, rd, imm):
        """Any 64-bit constant: MOVZ/MOVN + MOVKs (the shortest of the two)."""
        v = int(imm) & 0xFFFFFFFFFFFFFFFF
        parts = [(v >> (16 * k)) & 0xFFFF for k in range(4)]
        inv = [p ^ 0xFFFF for p in parts]
        nz = sum(1 for p in parts if p)
        nn = sum(1 for p in inv if p)
        if nz == 0:
            self.w(0xD2800000 | rd)                              # movz rd, #0
            return
        if nn == 0:
            self.w(0x92800000 | rd)                              # movn rd, #0 (all ones)
            return
        if nn < nz:
            first = next(k for k in range(4) if inv[k])
            self.w(0x92800000 | (first << 21) | (inv[first] << 5) | rd)    # movn
            for k in range(4):
                if k != first and inv[k]:
                    self.w(0xF2800000 | (k << 21) | (parts[k] << 5) | rd)  # movk
            return
        first = next(k for k in range(4) if parts[k])
        self.w(0xD2800000 | (first << 21) | (parts[first] << 5) | rd)      # movz
        for k in range(4):
            if k != first and parts[k]:
                self.w(0xF2800000 | (k << 21) | (parts[k] << 5) | rd)      # movk

    # ---- arithmetic -----------------------------------------------------------------------------------
    REG3 = {"add": 0x8B000000, "adds": 0xAB000000, "sub": 0xCB000000, "subs": 0xEB000000, "and": 0x8A000000,
            "ands": 0xEA000000, "or": 0xAA000000, "xor": 0xCA000000, "sdiv": 0x9AC00C00, "udiv": 0x9AC00800,
            "shl": 0x9AC02000, "shr": 0x9AC02400, "sar": 0x9AC02800}

    def op3(self, op, rd, rn, rm):
        self.w(self.REG3[op] | (rm << 16) | (rn << 5) | rd)

    def mul(self, rd, rn, rm):
        self.w(0x9B007C00 | (rm << 16) | (rn << 5) | rd)                   # madd rd, rn, rm, xzr

    def msub(self, rd, rn, rm, ra):                                        # rd = ra - rn*rm
        self.w(0x9B008000 | (rm << 16) | (ra << 10) | (rn << 5) | rd)

    def smulh(self, rd, rn, rm):
        self.w(0x9B407C00 | (rm << 16) | (rn << 5) | rd)

    def umulh(self, rd, rn, rm):
        self.w(0x9BC07C00 | (rm << 16) | (rn << 5) | rd)

    IMM = {"add": 0x91000000, "adds": 0xB1000000, "sub": 0xD1000000, "subs": 0xF1000000}

    def addsub_imm(self, op, rd, rn, imm):
        """add/sub with a 12-bit (optionally <<12) immediate; rn/rd may be SP (not for the flag forms' rd)."""
        if imm < 0:
            op = {"add": "sub", "sub": "add", "adds": "subs", "subs": "adds"}[op]
            imm = -imm
        if imm < 4096:
            self.w(self.IMM[op] | (imm << 10) | (rn << 5) | rd)
        elif imm & 0xFFF == 0 and imm < (1 << 24):
            self.w(self.IMM[op] | (1 << 22) | ((imm >> 12) << 10) | (rn << 5) | rd)
        else:
            raise ValueError("immediate too large")

    def fits_imm12(self, imm):
        a = abs(imm)
        return a < 4096 or (a & 0xFFF == 0 and a < (1 << 24))

    def shift_i(self, op, rd, rn, n):
        n &= 63
        if op == "shl":
            self.w(0xD3400000 | (((64 - n) & 63) << 16) | ((63 - n) << 10) | (rn << 5) | rd)   # ubfm
        elif op == "shr":
            self.w(0xD3400000 | (n << 16) | (63 << 10) | (rn << 5) | rd)                       # ubfm
        else:
            self.w(0x93400000 | (n << 16) | (63 << 10) | (rn << 5) | rd)                       # sbfm

    def neg(self, rd, rm):
        self.w(0xCB0003E0 | (rm << 16) | rd)                    # sub rd, xzr, rm

    def cmp_rr(self, rn, rm):
        self.op3("subs", XZR, rn, rm)

    def cmp_ri(self, rn, imm):
        self.addsub_imm("subs", XZR, rn, imm)

    def tst1(self, rn):
        """tst rn, #1 (the Int tag bit)."""
        self.w(0xF240001F | (rn << 5))

    def cset(self, rd, cc):
        self.w(0x9A9F07E0 | (COND[invert(cc)] << 12) | rd)    # csinc rd, xzr, xzr, !cc

    # ---- memory ---------------------------------------------------------------------------------------
    # (size, unsigned-offset opcode, unscaled opcode) for loads/stores of X, W, B and D registers
    MEM = {"ldr": (8, 0xF9400000, 0xF8400000), "str": (8, 0xF9000000, 0xF8000000),
           "ldrw": (4, 0xB9400000, 0xB8400000), "strw": (4, 0xB9000000, 0xB8000000),
           "ldrb": (1, 0x39400000, 0x38400000), "strb": (1, 0x39000000, 0x38000000),
           "ldrd": (8, 0xFD400000, 0xFC400000), "strd": (8, 0xFD000000, 0xFC000000)}

    def mem(self, op, rt, rn, off):
        size, uns, unscaled = self.MEM[op]
        if 0 <= off < 4096 * size and off % size == 0:
            self.w(uns | ((off // size) << 10) | (rn << 5) | rt)
        elif -256 <= off < 256:
            self.w(unscaled | ((off & 0x1FF) << 12) | (rn << 5) | rt)
        else:
            if rn == X16 or (rt == X16 and op in ("str", "strw", "strb")):
                raise ValueError("X16 is the address scratch register")
            self.mov_ri(X16, off)
            self.op3("add", X16, rn, X16) if rn != SP else self.add_sp(X16)
            self.w(uns | (X16 << 5) | rt)

    def add_sp(self, rd):
        """rd = sp + rd (extended-register form)."""
        self.w(0x8B206000 | (rd << 16) | (SP << 5) | rd)        # add rd, sp, rd, uxtx

    def load(self, rt, rn, off=0):
        self.mem("ldr", rt, rn, off)

    def store(self, rn, off, rt):
        self.mem("str", rt, rn, off)

    def stp_pre(self, rt, rt2, rn, off):
        self.w(0xA9800000 | (((off // 8) & 0x7F) << 15) | (rt2 << 10) | (rn << 5) | rt)

    def ldp_post(self, rt, rt2, rn, off):
        self.w(0xA8C00000 | (((off // 8) & 0x7F) << 15) | (rt2 << 10) | (rn << 5) | rt)

    def adr_sym(self, rd, target):
        """rd = address of a data/code symbol (ADRP + ADD, patched by the linker)."""
        self.fixups.append((len(self.code), target, "page"))
        self.w(0x90000000 | rd)
        self.fixups.append((len(self.code), target, "lo12"))
        self.w(0x91000000 | (rd << 5) | rd)

    # ---- branches -------------------------------------------------------------------------------------
    def b(self, target):
        self.branches.append((len(self.code), target, "b26"))
        self.w(0x14000000)

    def bl(self, target):
        self.branches.append((len(self.code), target, "b26"))
        self.w(0x94000000)

    def bcc(self, cc, target):
        self.branches.append((len(self.code), target, "b19"))
        self.w(0x54000000 | COND[cc])

    def cbz(self, rt, target):
        self.branches.append((len(self.code), target, "b19"))
        self.w(0xB4000000 | rt)

    def cbnz(self, rt, target):
        self.branches.append((len(self.code), target, "b19"))
        self.w(0xB5000000 | rt)

    def blr(self, rn):
        self.w(0xD63F0000 | (rn << 5))

    def ret(self):
        self.w(0xD65F03C0)

    def svc(self):
        self.w(0xD4000001)

    def udf(self):
        self.w(0x00000000)

    # ---- floating point (double) ----------------------------------------------------------------------
    FOP = {"add": 0x1E602800, "sub": 0x1E603800, "mul": 0x1E600800, "div": 0x1E601800}

    def fop(self, op, dd, dn, dm):
        self.w(self.FOP[op] | (dm << 16) | (dn << 5) | dd)

    def fsqrt(self, dd, dn):
        self.w(0x1E61C000 | (dn << 5) | dd)

    def fmov_dd(self, dd, dn):
        if dd != dn:
            self.w(0x1E604000 | (dn << 5) | dd)

    def fmov_dx(self, dd, xn):          # d <- x (bits)
        self.w(0x9E670000 | (xn << 5) | dd)

    def fmov_xd(self, xd, dn):          # x <- d (bits)
        self.w(0x9E660000 | (dn << 5) | xd)

    def fcmp(self, dn, dm):
        self.w(0x1E602000 | (dm << 16) | (dn << 5))

    def scvtf(self, dd, xn):
        self.w(0x9E620000 | (xn << 5) | dd)

    def fcvtzs(self, xd, dn):
        self.w(0x9E780000 | (dn << 5) | xd)

    def fload(self, dt, rn, off):
        self.mem("ldrd", dt, rn, off)

    def fstore(self, rn, off, dt):
        self.mem("strd", dt, rn, off)
