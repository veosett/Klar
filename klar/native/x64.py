"""A small x86-64 assembler: encodes the instructions the Klar backend needs.

Only RIP-relative and register-relative addressing is used for code/data, so the
same machine code works for both ELF (Linux) and PE (Windows) executables.
"""
import struct

RAX, RCX, RDX, RBX, RSP, RBP, RSI, RDI = range(8)
R8, R9, R10, R11, R12, R13, R14, R15 = range(8, 16)
XMM0, XMM1, XMM2, XMM3 = range(4)

CC = {"o": 0, "no": 1, "b": 2, "ae": 3, "e": 4, "ne": 5, "be": 6, "a": 7, "s": 8, "ns": 9,
      "p": 10, "np": 11, "l": 12, "ge": 13, "le": 14, "g": 15}

ALU = {"add": (0x01, 0), "or": (0x09, 1), "and": (0x21, 4), "sub": (0x29, 5), "xor": (0x31, 6), "cmp": (0x39, 7)}


class Asm:
    def __init__(self):
        self.code = bytearray()
        self.labels = {}           # local label -> offset
        self.fixups = []           # (pos, target, addend): rel32 to a label or external symbol
        self._n = 0

    # ---- labels -----------------------------------------------------------
    def new_label(self, hint="L"):
        self._n += 1
        return f".{hint}{self._n}"

    def label(self, name):
        if name in self.labels:
            raise ValueError(f"duplicate label {name}")
        self.labels[name] = len(self.code)

    def here(self):
        return len(self.code)

    def b(self, *bs):
        self.code.extend(bs)

    def d32(self, v):
        self.code += struct.pack("<i", v)

    def d64(self, v):
        self.code += struct.pack("<q", v)

    def rel32(self, target, addend=0):
        self.fixups.append((len(self.code), target, addend))
        self.d32(0)

    # ---- encoding helpers -------------------------------------------------
    def rex(self, w, r, x, b, force=False):
        v = 0x40 | (w << 3) | ((r >> 3) << 2) | ((x >> 3) << 1) | (b >> 3)
        if v != 0x40 or force:
            self.b(v)

    def modrm_mem(self, reg, base, disp):
        """[base + disp8/disp32] addressing (base may be RSP/R12 -> SIB)."""
        short = -128 <= disp < 128
        self.b((0x40 if short else 0x80) | ((reg & 7) << 3) | (base & 7))
        if base & 7 == RSP:
            self.b(0x24)
        if short:
            self.b(disp & 0xFF)
        else:
            self.d32(disp)

    def modrm_rr(self, reg, rm):
        self.b(0xC0 | ((reg & 7) << 3) | (rm & 7))

    def modrm_rip(self, reg, target, addend=0):
        self.b(0x05 | ((reg & 7) << 3))
        self.rel32(target, addend)

    # ---- moves --------------------------------------------------------------
    def mov_rr(self, dst, src):
        if dst == src:
            return
        self.rex(1, src, 0, dst)
        self.b(0x89)
        self.modrm_rr(src, dst)

    def mov_ri(self, dst, imm):
        imm = int(imm)
        if -2 ** 31 <= imm < 2 ** 31:
            self.rex(1, 0, 0, dst)
            self.b(0xC7)
            self.modrm_rr(0, dst)
            self.d32(imm)
        else:
            if imm >= 2 ** 63:
                imm -= 2 ** 64
            self.rex(1, 0, 0, dst)
            self.b(0xB8 + (dst & 7))
            self.d64(imm)

    def load(self, dst, base, disp=0):          # mov dst, qword [base+disp]
        self.rex(1, dst, 0, base)
        self.b(0x8B)
        self.modrm_mem(dst, base, disp)

    def store(self, base, disp, src):           # mov qword [base+disp], src
        self.rex(1, src, 0, base)
        self.b(0x89)
        self.modrm_mem(src, base, disp)

    def load8(self, dst, base, disp=0):         # movzx dst, byte [base+disp]
        self.rex(1, dst, 0, base)
        self.b(0x0F, 0xB6)
        self.modrm_mem(dst, base, disp)

    def store8(self, base, disp, src):          # mov byte [base+disp], src8
        self.rex(0, src, 0, base, force=src >= 4)
        self.b(0x88)
        self.modrm_mem(src, base, disp)

    def load32(self, dst, base, disp=0):        # mov dst32, dword [base+disp] (zero-extends)
        self.rex(0, dst, 0, base)
        self.b(0x8B)
        self.modrm_mem(dst, base, disp)

    def store32(self, base, disp, src):
        self.rex(0, src, 0, base)
        self.b(0x89)
        self.modrm_mem(src, base, disp)

    def lea(self, dst, base, disp):
        self.rex(1, dst, 0, base)
        self.b(0x8D)
        self.modrm_mem(dst, base, disp)

    def lea_rip(self, dst, target, addend=0):
        self.rex(1, dst, 0, 0)
        self.b(0x8D)
        self.modrm_rip(dst, target, addend)

    def load_rip(self, dst, target):            # mov dst, qword [rip+target]
        self.rex(1, dst, 0, 0)
        self.b(0x8B)
        self.modrm_rip(dst, target)

    def store_rip(self, target, src):
        self.rex(1, src, 0, 0)
        self.b(0x89)
        self.modrm_rip(src, target)

    # ---- arithmetic -----------------------------------------------------------
    def alu_rr(self, op, dst, src):
        opc, _ = ALU[op]
        self.rex(1, src, 0, dst)
        self.b(opc)
        self.modrm_rr(src, dst)

    def alu_ri(self, op, dst, imm):
        _, ext = ALU[op]
        self.rex(1, 0, 0, dst)
        if -128 <= imm < 128:
            self.b(0x83)
            self.modrm_rr(ext, dst)
            self.b(imm & 0xFF)
        else:
            self.b(0x81)
            self.modrm_rr(ext, dst)
            self.d32(imm)

    def test_rr(self, a, b):
        self.rex(1, b, 0, a)
        self.b(0x85)
        self.modrm_rr(b, a)

    def test_ri8(self, reg, imm):              # test reg8, imm8 (low byte)
        self.rex(0, 0, 0, reg, force=reg >= 4)
        self.b(0xF6)
        self.modrm_rr(0, reg)
        self.b(imm & 0xFF)

    def imul_rr(self, dst, src):
        self.rex(1, dst, 0, src)
        self.b(0x0F, 0xAF)
        self.modrm_rr(dst, src)

    def imul_rri(self, dst, src, imm):           # dst = src * imm32
        self.rex(1, dst, 0, src)
        if -128 <= imm < 128:
            self.b(0x6B)
            self.modrm_rr(dst, src)
            self.b(imm & 0xFF)
        else:
            self.b(0x69)
            self.modrm_rr(dst, src)
            self.d32(imm)

    def cqo(self):
        self.b(0x48, 0x99)

    def idiv(self, src):
        self.rex(1, 0, 0, src)
        self.b(0xF7)
        self.modrm_rr(7, src)

    def div(self, src):                          # unsigned rdx:rax / src
        self.rex(1, 0, 0, src)
        self.b(0xF7)
        self.modrm_rr(6, src)

    def imul1(self, src):                        # signed rdx:rax = rax * src
        self.rex(1, 0, 0, src)
        self.b(0xF7)
        self.modrm_rr(5, src)

    def mul(self, src):                          # unsigned rdx:rax = rax * src
        self.rex(1, 0, 0, src)
        self.b(0xF7)
        self.modrm_rr(4, src)

    def neg(self, r):
        self.rex(1, 0, 0, r)
        self.b(0xF7)
        self.modrm_rr(3, r)

    def not_(self, r):
        self.rex(1, 0, 0, r)
        self.b(0xF7)
        self.modrm_rr(2, r)

    def shift_cl(self, kind, r):                 # kind: shl sar shr
        ext = {"shl": 4, "shr": 5, "sar": 7}[kind]
        self.rex(1, 0, 0, r)
        self.b(0xD3)
        self.modrm_rr(ext, r)

    def shift_i(self, kind, r, n):
        ext = {"shl": 4, "shr": 5, "sar": 7}[kind]
        self.rex(1, 0, 0, r)
        self.b(0xC1)
        self.modrm_rr(ext, r)
        self.b(n & 63)

    def setcc(self, cc, r):                      # setcc r8 ; movzx r64, r8
        self.rex(0, 0, 0, r, force=r >= 4)
        self.b(0x0F, 0x90 + CC[cc])
        self.modrm_rr(0, r)
        self.rex(1, r, 0, r)
        self.b(0x0F, 0xB6)
        self.modrm_rr(r, r)

    def cmov(self, cc, dst, src):
        self.rex(1, dst, 0, src)
        self.b(0x0F, 0x40 + CC[cc])
        self.modrm_rr(dst, src)

    # ---- control flow -------------------------------------------------------------
    def jmp(self, target):
        self.b(0xE9)
        self.rel32(target)

    def jcc(self, cc, target):
        self.b(0x0F, 0x80 + CC[cc])
        self.rel32(target)

    def call(self, target):
        self.b(0xE8)
        self.rel32(target)

    def call_r(self, r):
        self.rex(0, 0, 0, r)
        self.b(0xFF)
        self.modrm_rr(2, r)

    def call_rip(self, target):                  # call qword [rip+target] (PE import slots)
        self.b(0xFF)
        self.modrm_rip(2, target)

    def ret(self):
        self.b(0xC3)

    def push(self, r):
        self.rex(0, 0, 0, r)
        self.b(0x50 + (r & 7))

    def pop(self, r):
        self.rex(0, 0, 0, r)
        self.b(0x58 + (r & 7))

    def syscall(self):
        self.b(0x0F, 0x05)

    def ud2(self):
        self.b(0x0F, 0x0B)

    # ---- SSE2 scalar double -----------------------------------------------------------
    def movq_xr(self, x, r):                     # movq xmm, r64
        self.b(0x66)
        self.rex(1, x, 0, r)
        self.b(0x0F, 0x6E)
        self.modrm_rr(x, r)

    def movq_rx(self, r, x):                     # movq r64, xmm
        self.b(0x66)
        self.rex(1, x, 0, r)
        self.b(0x0F, 0x7E)
        self.modrm_rr(x, r)

    def sse(self, op, dst, src):
        opc = {"add": 0x58, "mul": 0x59, "sub": 0x5C, "div": 0x5E, "sqrt": 0x51}[op]
        self.b(0xF2)
        self.rex(0, dst, 0, src)
        self.b(0x0F, opc)
        self.modrm_rr(dst, src)

    def ucomisd(self, a, b):
        self.b(0x66)
        self.rex(0, a, 0, b)
        self.b(0x0F, 0x2E)
        self.modrm_rr(a, b)

    def cvtsi2sd(self, x, r):
        self.b(0xF2)
        self.rex(1, x, 0, r)
        self.b(0x0F, 0x2A)
        self.modrm_rr(x, r)

    def cvttsd2si(self, r, x):
        self.b(0xF2)
        self.rex(1, r, 0, x)
        self.b(0x0F, 0x2C)
        self.modrm_rr(r, x)

    # ---- x87 (sin, cos, ln, exp) ---------------------------------------------------------
    def fld_m(self, base, disp):
        self.rex(0, 0, 0, base)
        self.b(0xDD)
        self.modrm_mem(0, base, disp)

    def fstp_m(self, base, disp):
        self.rex(0, 0, 0, base)
        self.b(0xDD)
        self.modrm_mem(3, base, disp)

    def x87(self, name):
        ops = {"fsin": (0xD9, 0xFE), "fcos": (0xD9, 0xFF), "fldln2": (0xD9, 0xED), "fyl2x": (0xD9, 0xF1),
               "fldl2e": (0xD9, 0xEA), "f2xm1": (0xD9, 0xF0), "fscale": (0xD9, 0xFD), "frndint": (0xD9, 0xFC),
               "fld1": (0xD9, 0xE8), "fxch": (0xD9, 0xC9), "fmulp": (0xDE, 0xC9), "fsubp": (0xDE, 0xE9),
               "faddp": (0xDE, 0xC1), "fstp1": (0xDD, 0xD9), "fld0": (0xD9, 0xC0), "fprem": (0xD9, 0xF8),
               "fldpi": (0xD9, 0xEB), "fsubrp": (0xDE, 0xE1), "fsub01": (0xD8, 0xE1)}
        self.b(*ops[name])

    # ---- finishing ----------------------------------------------------------------------
    def resolve_local(self):
        """Resolve fixups to local labels; return the ones that target external symbols."""
        rest = []
        for pos, target, addend in self.fixups:
            if target in self.labels:
                rel = self.labels[target] + addend - (pos + 4)
                self.code[pos:pos + 4] = struct.pack("<i", rel)
            else:
                rest.append((pos, target, addend))
        self.fixups = rest
        return rest
