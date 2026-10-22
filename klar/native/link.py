"""Writes standalone executables: ELF64 (Linux x86-64 and arm64, no libc) and PE32+ (Windows, imports only
kernel32.dll).

Input: one code blob (with fixups to data symbols / import slots: rel32 on x86-64, ADRP page / ADD low-12-bit
fields on arm64) and one data blob (with absolute 64-bit pointer relocations), plus zero-initialised bss.
"""
import struct


def align(v, a):
    return (v + a - 1) // a * a


class Image:
    def __init__(self):
        self.code = bytearray()
        self.code_labels = {}
        self.code_fixups = []       # (pos, target, addend) rel32
        self.data = bytearray()
        self.data_syms = {}
        self.data_abs = []          # (data_offset, target_symbol, addend) -> absolute 64-bit address
        self.bss_size = 0
        self.bss_syms = {}
        self.imports = []           # Windows: kernel32 function names
        self.entry = "_start"
        self.machine = "x86_64"     # or "aarch64" (the fixups are then (pos, target, "page" | "lo12"))

    # ---- data helpers ---------------------------------------------------------
    def add_data(self, name, payload, alignment=8):
        while len(self.data) % alignment:
            self.data.append(0)
        self.data_syms[name] = len(self.data)
        self.data += payload
        return name

    def add_bss(self, name, size, alignment=16):
        self.bss_size = align(self.bss_size, alignment)
        self.bss_syms[name] = self.bss_size
        self.bss_size += size
        return name

    # ---- address resolution -----------------------------------------------------
    def _addresses(self, code_base, data_base, bss_base, import_slots):
        addr = {}
        for k, v in self.code_labels.items():
            addr[k] = code_base + v
        for k, v in self.data_syms.items():
            addr[k] = data_base + v
        for k, v in self.bss_syms.items():
            addr[k] = bss_base + v
        addr.update(import_slots)
        return addr

    def _patch(self, addr, code_base, data_base, absolute):
        code = bytearray(self.code)
        for pos, target, addend in self.code_fixups:
            if target not in addr:
                raise KeyError(f"unresolved symbol {target}")
            if addend == "page":                        # ADRP: the 4 KB page of the target, PC-relative
                delta = (addr[target] >> 12) - ((code_base + pos) >> 12)
                word, = struct.unpack_from("<I", code, pos)
                word |= ((delta & 3) << 29) | (((delta >> 2) & 0x7FFFF) << 5)
                struct.pack_into("<I", code, pos, word)
            elif addend == "lo12":                      # ADD: the offset inside that page
                word, = struct.unpack_from("<I", code, pos)
                struct.pack_into("<I", code, pos, word | ((addr[target] & 0xFFF) << 10))
            else:
                rel = addr[target] + addend - (code_base + pos + 4)
                code[pos:pos + 4] = struct.pack("<i", rel)
        data = bytearray(self.data)
        for off, target, addend in self.data_abs:
            data[off:off + 8] = struct.pack("<Q", absolute(addr[target] + addend))
        return code, data

    # ---- ELF ----------------------------------------------------------------------
    def write_elf(self, path):
        base = 0x400000
        arm = self.machine == "aarch64"
        page = 0x10000 if arm else 0x1000            # (arm64 kernels may use 64 KB pages)
        text_off = page
        text_vaddr = base + text_off
        data_off = align(text_off + len(self.code), page)
        data_vaddr = base + data_off
        bss_vaddr = data_vaddr + align(len(self.data), 16)
        addr = self._addresses(text_vaddr, data_vaddr, bss_vaddr, {})
        code, data = self._patch(addr, text_vaddr, data_vaddr, lambda a: a)
        ehdr = struct.pack("<4sBBBBB7sHHIQQQIHHHHHH", b"\x7fELF", 2, 1, 1, 0, 0, b"\0" * 7,
                           2, 0xB7 if arm else 0x3E, 1, addr[self.entry], 64, 0, 0, 64, 56, 2, 64, 0, 0)
        memsz_data = align(len(self.data), 16) + self.bss_size
        ph_text = struct.pack("<IIQQQQQQ", 1, 5, 0, base, base, text_off + len(code), text_off + len(code), page)
        ph_data = struct.pack("<IIQQQQQQ", 1, 6, data_off, data_vaddr, data_vaddr, len(data), max(memsz_data, 1), page)
        out = bytearray(ehdr + ph_text + ph_data)
        out += b"\0" * (text_off - len(out))
        out += code
        out += b"\0" * (data_off - len(out))
        out += data
        with open(path, "wb") as f:
            f.write(out)

    # ---- PE32+ ----------------------------------------------------------------------
    def write_pe(self, path):
        image_base = 0x140000000
        salign, falign = 0x1000, 0x200
        headers_size = 0x400
        text_rva = salign
        text_raw = headers_size
        text_vsize = len(self.code)
        data_rva = align(text_rva + text_vsize, salign)
        data_raw = align(text_raw + len(self.code), falign)
        data_fsize = align(len(self.data), 16)
        data_vsize = data_fsize + self.bss_size
        idata_rva = align(data_rva + max(data_vsize, 1), salign)
        idata_raw = align(data_raw + max(data_fsize, 1), falign)
        # ---- build the import section for kernel32.dll
        names = list(self.imports)
        n = len(names)
        desc_size = 20 * 2
        ilt_off = desc_size
        iat_off = ilt_off + 8 * (n + 1)
        hint_off = iat_off + 8 * (n + 1)
        hints = bytearray()
        hint_rvas = []
        for nm in names:
            hint_rvas.append(idata_rva + hint_off + len(hints))
            hints += struct.pack("<H", 0) + nm.encode() + b"\0"
            if len(hints) % 2:
                hints += b"\0"
        dll_off = hint_off + len(hints)
        dll_name = b"KERNEL32.dll\0"
        idata = bytearray(dll_off + len(dll_name))
        struct.pack_into("<IIIII", idata, 0, idata_rva + ilt_off, 0, 0, idata_rva + dll_off, idata_rva + iat_off)
        for i, r in enumerate(hint_rvas):
            struct.pack_into("<Q", idata, ilt_off + 8 * i, r)
            struct.pack_into("<Q", idata, iat_off + 8 * i, r)
        idata[hint_off:hint_off + len(hints)] = hints
        idata[dll_off:dll_off + len(dll_name)] = dll_name
        import_slots = {f"__imp_{nm}": image_base + idata_rva + iat_off + 8 * i for i, nm in enumerate(names)}
        addr = self._addresses(image_base + text_rva, image_base + data_rva, image_base + data_rva + data_fsize,
                               import_slots)
        code, data = self._patch(addr, image_base + text_rva, image_base + data_rva, lambda a: a)
        idata_vsize = len(idata)
        size_of_image = align(idata_rva + idata_vsize, salign)
        # ---- headers
        dos = bytearray(0x80)
        dos[0:2] = b"MZ"
        struct.pack_into("<I", dos, 0x3C, 0x80)
        coff = struct.pack("<4sHHIIIHH", b"PE\0\0", 0x8664, 3, 0, 0, 0, 240, 0x0023)
        entry_rva = addr[self.entry] - image_base
        opt = struct.pack("<HBBIIIII", 0x20B, 14, 0, align(len(code), falign), align(data_fsize, falign) +
                          align(idata_vsize, falign), 0, entry_rva, text_rva)
        opt += struct.pack("<QIIHHHHHHIIIIHHQQQQII", image_base, salign, falign, 6, 0, 0, 0, 6, 0, 0,
                           size_of_image, headers_size, 0, 3, 0x8100,
                           0x20000000, 0x1000, 0x100000, 0x1000, 0, 16)
        dirs = [(0, 0)] * 16
        dirs[1] = (idata_rva, desc_size)
        dirs[12] = (idata_rva + iat_off, 8 * (n + 1))
        for rva, size in dirs:
            opt += struct.pack("<II", rva, size)
        assert len(opt) == 240

        def section(name, vsize, rva, rawsize, raw, flags):
            return struct.pack("<8sIIIIIIHHI", name, vsize, rva, rawsize, raw, 0, 0, 0, 0, flags)

        sects = section(b".text", max(text_vsize, 1), text_rva, align(len(code), falign), text_raw, 0x60000020)
        sects += section(b".data", max(data_vsize, 1), data_rva, align(data_fsize, falign), data_raw, 0xC0000040)
        sects += section(b".idata", idata_vsize, idata_rva, align(idata_vsize, falign), idata_raw, 0xC0000040)
        out = bytearray(dos + coff + opt + sects)
        out += b"\0" * (headers_size - len(out))
        out += code
        out += b"\0" * (data_raw - len(out))
        out += data
        out += b"\0" * (idata_raw - len(out))
        out += idata
        out += b"\0" * (align(len(out), falign) - len(out))
        with open(path, "wb") as f:
            f.write(out)
