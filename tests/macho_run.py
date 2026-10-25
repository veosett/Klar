"""Runs a Klar macOS executable (Mach-O x86-64, `klar build --target macos`) on Linux, for the tests.

    python tests/macho_run.py program.macho [args...]

The machine code runs in the Unicorn CPU emulator (`pip install unicorn`); its BSD system calls (number 0x2000000 + n;
failure = carry flag set and the errno in RAX) are carried out on the host by Python: files, directories, pipes,
fork (os.fork copies the emulator too), wait4, execve, poll, sysctl hw.ncpu and fcntl F_GETPATH. Only what Klar's
runtime uses is there. This checks the macOS layer of both compilers (system call numbers, flags, structure layouts
as macOS defines them); it cannot replace a run on a real Mac.
"""
import os
import select
import struct
import sys
import time

from unicorn import UC_ARCH_X86, UC_HOOK_INSN, UC_MODE_64, UC_PROT_ALL, Uc, UcError
from unicorn.x86_const import (UC_X86_INS_SYSCALL, UC_X86_REG_EFLAGS, UC_X86_REG_R8, UC_X86_REG_R9, UC_X86_REG_R10,
                               UC_X86_REG_RAX, UC_X86_REG_RDI, UC_X86_REG_RDX, UC_X86_REG_RIP, UC_X86_REG_RSI,
                               UC_X86_REG_RSP)

PAGE = 0x1000
STACK_TOP = 0x7FF000000000
STACK_SIZE = 1 << 20
ENOSYS = 78


def align(v, a=PAGE):
    return (v + a - 1) // a * a


class Exit(Exception):
    def __init__(self, code):
        self.code = code


class Machine:
    def __init__(self, path, argv):
        self.uc = Uc(UC_ARCH_X86, UC_MODE_64)
        self.heap = 0x300000000
        self.dirs = {}                       # fd -> remaining directory entries (getdirentries64)
        self.exit_code = None
        entry = self.load(open(path, "rb").read())
        self.uc.reg_write(UC_X86_REG_RSP, self.stack(argv))
        self.entry = entry
        self.uc.hook_add(UC_HOOK_INSN, self.on_syscall, None, 1, 0, UC_X86_INS_SYSCALL)

    # ---- loading -------------------------------------------------------------------------
    def load(self, image):
        magic, cpu, _, ftype, ncmds, _, _, _ = struct.unpack_from("<IiiIIIII", image, 0)
        assert magic == 0xFEEDFACF and cpu == 0x01000007 and ftype == 2, "not a Mach-O x86-64 executable"
        off = 32
        entry = None
        for _ in range(ncmds):
            cmd, size = struct.unpack_from("<II", image, off)
            if cmd == 0x19:                                  # LC_SEGMENT_64
                name, vmaddr, vmsize, fileoff, filesize = struct.unpack_from("<16sQQQQ", image, off + 8)
                if vmaddr != 0 or fileoff != 0 or filesize != 0:
                    if not name.startswith(b"__PAGEZERO"):
                        self.uc.mem_map(vmaddr, align(vmsize), UC_PROT_ALL)
                        self.uc.mem_write(vmaddr, image[fileoff:fileoff + filesize])
            elif cmd == 0x5:                                 # LC_UNIXTHREAD
                flavor, count = struct.unpack_from("<II", image, off + 8)
                assert flavor == 4 and count == 42
                entry = struct.unpack_from("<21Q", image, off + 16)[16]
            off += size
        assert entry is not None, "no LC_UNIXTHREAD"
        return entry

    def stack(self, argv):
        """argc, argv[], NULL, envp[], NULL — as the macOS kernel lays out a static executable's stack."""
        base = STACK_TOP - STACK_SIZE
        self.uc.mem_map(base, STACK_SIZE, UC_PROT_ALL)
        strings = bytearray()
        offsets = []
        env = [f"{k}={v}" for k, v in os.environ.items()]
        for s in list(argv) + env:
            offsets.append(len(strings))
            strings += s.encode() + b"\0"
        str_at = STACK_TOP - align(len(strings) + 16, 16)
        self.uc.mem_write(str_at, bytes(strings))
        words = [len(argv)] + [str_at + o for o in offsets[:len(argv)]] + [0] + \
            [str_at + o for o in offsets[len(argv):]] + [0, 0]
        sp = (str_at - 8 * len(words)) & ~15
        self.uc.mem_write(sp, struct.pack(f"<{len(words)}Q", *words))
        return sp

    # ---- memory helpers ------------------------------------------------------------------------
    def cstr(self, p):
        out = bytearray()
        while True:
            chunk = bytes(self.uc.mem_read(p, 64))
            k = chunk.find(b"\0")
            if k >= 0:
                return bytes(out + chunk[:k])
            out += chunk
            p += 64

    def ptrs(self, p):
        out = []
        while True:
            v = struct.unpack("<Q", bytes(self.uc.mem_read(p, 8)))[0]
            if v == 0:
                return out
            out.append(self.cstr(v))
            p += 8

    def mmap(self, size):
        size = align(size)
        at = self.heap
        self.uc.mem_map(at, size, UC_PROT_ALL)
        self.heap += size + PAGE
        return at

    # ---- system calls ----------------------------------------------------------------------------
    def on_syscall(self, uc, _):
        nr = uc.reg_read(UC_X86_REG_RAX)
        args = [uc.reg_read(r) for r in (UC_X86_REG_RDI, UC_X86_REG_RSI, UC_X86_REG_RDX, UC_X86_REG_R10,
                                         UC_X86_REG_R8, UC_X86_REG_R9)]
        rdx = None
        try:
            if nr & 0xFF000000 != 0x2000000:
                raise OSError(ENOSYS, "not a BSD call")
            res = self.call(nr & 0xFFFFFF, args)
            if isinstance(res, tuple):
                res, rdx = res
            err = False
        except OSError as ex:
            res, err = ex.errno or ENOSYS, True
        except Exit as ex:
            self.exit_code = ex.code
            uc.emu_stop()
            return
        flags = uc.reg_read(UC_X86_REG_EFLAGS)
        uc.reg_write(UC_X86_REG_EFLAGS, flags | 1 if err else flags & ~1)
        uc.reg_write(UC_X86_REG_RAX, res & 0xFFFFFFFFFFFFFFFF)
        if rdx is not None:
            uc.reg_write(UC_X86_REG_RDX, rdx)

    def call(self, n, a):
        uc = self.uc
        if n == 1:                                              # exit
            raise Exit(a[0] & 0xFF)
        if n == 3:                                              # read
            data = os.read(a[0], a[2])
            uc.mem_write(a[1], data)
            return len(data)
        if n == 4:                                              # write
            return os.write(a[0], bytes(uc.mem_read(a[1], a[2])))
        if n == 5:                                              # open
            flags = 0
            if a[1] & 3 == 1:
                flags |= os.O_WRONLY
            if a[1] & 0x200:
                flags |= os.O_CREAT
            if a[1] & 0x400:
                flags |= os.O_TRUNC
            path = self.cstr(a[0])
            fd = os.open(path, flags, a[2])
            if os.path.isdir(path):
                self.dirs[fd] = [b".", b".."] + os.listdir(path)
            return fd
        if n == 6:                                              # close
            self.dirs.pop(a[0], None)
            os.close(a[0])
            return 0
        if n == 2:                                              # fork: RDX = 1 in the child
            pid = os.fork()
            return (os.getppid(), 1) if pid == 0 else (pid, 0)
        if n == 7:                                              # wait4
            _, status = os.waitpid(a[0], 0)
            if a[1]:
                uc.mem_write(a[1], struct.pack("<i", status))
            return a[0]
        if n == 10:                                             # unlink
            os.unlink(self.cstr(a[0]))
            return 0
        if n == 12:                                             # chdir
            os.chdir(self.cstr(a[0]))
            return 0
        if n == 15:                                             # chmod
            os.chmod(self.cstr(a[0]), a[1])
            return 0
        if n == 37:                                             # kill
            os.kill(a[0], a[1])
            return 0
        if n == 42:                                             # pipe: fds in RAX, RDX
            r, w = os.pipe()
            return (r, w)
        if n == 58:                                             # readlink(path, buf, n): EINVAL if not a link
            target = os.readlink(self.cstr(a[0]))[:a[2]]
            uc.mem_write(a[1], target)
            return len(target)
        if n == 59:                                             # execve
            path = self.cstr(a[0])
            os.execve(path, self.ptrs(a[1]), {k.decode(): v.decode() for k, _, v in
                                              (e.partition(b"=") for e in self.ptrs(a[2]))})
        if n == 90:                                             # dup2
            os.dup2(a[0], a[1])
            return a[1]
        if n == 92:                                             # fcntl(fd, F_GETPATH, buf)
            if a[1] != 50:
                raise OSError(ENOSYS, "fcntl")
            path = os.readlink(f"/proc/self/fd/{a[0]}").encode()
            uc.mem_write(a[2], path + b"\0")
            return 0
        if n == 116:                                            # gettimeofday
            t = time.time_ns() // 1000
            if a[0]:
                uc.mem_write(a[0], struct.pack("<qi4x", t // 1000000, t % 1000000))
            return 0
        if n == 136:                                            # mkdir
            os.mkdir(self.cstr(a[0]), a[1])
            return 0
        if n == 197:                                            # mmap (anonymous only)
            return self.mmap(a[1])
        if n == 202:                                            # sysctl: hw.ncpu only
            name = struct.unpack("<ii", bytes(uc.mem_read(a[0], 8)))
            if name != (6, 3):
                raise OSError(ENOSYS, "sysctl")
            uc.mem_write(a[2], struct.pack("<i", os.cpu_count() or 1))
            uc.mem_write(a[3], struct.pack("<Q", 4))
            return 0
        if n == 230:                                            # poll(fds, n, timeout)
            p = select.poll()
            raw = bytes(uc.mem_read(a[0], 8 * a[1]))
            entries = [struct.unpack_from("<ihh", raw, 8 * i) for i in range(a[1])]
            for fd, ev, _ in entries:
                if fd >= 0:
                    p.register(fd, ev)
            got = dict(p.poll(None if a[2] & 0x80000000 else a[2]))
            for i, (fd, ev, _) in enumerate(entries):
                uc.mem_write(a[0] + 8 * i, struct.pack("<ihh", fd, ev, got.get(fd, 0)))
            return len(got)
        if n == 338:                                            # stat64: st_mode at offset 4
            st = os.stat(self.cstr(a[0]))
            buf = bytearray(144)
            struct.pack_into("<iHH", buf, 0, 0, st.st_mode & 0xFFFF, 1)
            struct.pack_into("<q", buf, 96, st.st_size)
            uc.mem_write(a[1], bytes(buf))
            return 0
        if n == 344:                                            # getdirentries64
            names = self.dirs.get(a[0])
            if names is None:
                raise OSError(20, "not a directory")
            out = bytearray()
            while names:
                raw = names[0]
                reclen = align(21 + len(raw) + 1, 8)
                if len(out) + reclen > a[2]:
                    break
                out += struct.pack("<QQHHB", 1, 0, reclen, len(raw), 8) + raw + b"\0" * (reclen - 21 - len(raw))
                names.pop(0)
            uc.mem_write(a[1], bytes(out))
            return len(out)
        raise OSError(ENOSYS, f"system call {n}")

    def run(self):
        try:
            self.uc.emu_start(self.entry, 0)
        except UcError as ex:
            rip = self.uc.reg_read(UC_X86_REG_RIP)
            sys.stderr.write(f"macho_run: CPU error {ex} at {rip:#x}\n")
            return 139
        if self.exit_code is None:
            sys.stderr.write("macho_run: the program stopped without exit\n")
            return 139
        return self.exit_code


def main(argv):
    if len(argv) < 2:
        print(__doc__.strip().split("\n")[2].strip())
        return 2
    return Machine(argv[1], argv[1:]).run()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
