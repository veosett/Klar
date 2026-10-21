"""KIR — Klar's low-level intermediate representation.

Every value is one 64-bit word held in a virtual register (vreg):
  Int   -> tagged: (n << 1) | 1 for 63-bit values, otherwise a pointer to a bignum object
  Float -> IEEE-754 bits, Bool -> 0/1, Unit -> 0, Word -> raw machine word
  everything else -> pointer to a reference-counted heap object [rc][type-descriptor][...]

Instructions are tuples; the first element is the opcode:
  ("const", d, imm)            ("mov", d, s)               ("addr", d, symbol)
  ("bin", op, d, a, b)         op: add sub mul sdiv srem and or xor shl shr sar   (raw words)
  ("cmp", cc, d, a, b)         cc: eq ne lt le gt ge ult                          (raw words -> 0/1)
  ("fbin", op, d, a, b)        op: add sub mul div                                 (doubles)
  ("fcmp", cc, d, a, b)        ("i2f", d, a) ("f2i", d, a) ("fun", op, d, a)   op: sqrt sin cos ln exp
  ("iop", op, d, a, b, span)   tagged Int add sub mul div mod (fast path inline, bignum/zero -> runtime)
  ("icmp", cc, d, a, b)        ("ineg", d, a)
  ("load", d, base, off)  ("store", base, off, v)  ("load8"/"store8"/"load32"/"store32" ...)
  ("call", d, fn, [args])      ("callind", d, fnptr_reg, [args])
  ("retain", kind, v)          ("release", kind, v)        kind: "obj" | "int"
  ("label", L)  ("jmp", L)  ("br", c, Ltrue, Lfalse)  ("ret", v)
  ("enter", name_symbol)  ("leave",)  ("site", span_symbol)       shadow call stack for error traces
"""


class Fn:
    def __init__(self, name, nparams, klar_name=None):
        self.name = name
        self.klar_name = klar_name or name
        self.nparams = nparams
        self.nregs = nparams
        self.code = []
        self._labels = 0

    def reg(self):
        r = self.nregs
        self.nregs += 1
        return r

    def label(self, hint="L"):
        self._labels += 1
        return f".{self.name}.{hint}{self._labels}"

    def emit(self, *ins):
        self.code.append(ins)

    def const(self, imm):
        d = self.reg()
        self.emit("const", d, imm)
        return d
