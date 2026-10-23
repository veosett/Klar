"""The fakes behind the effects of tests: `test "t" uses fs, time, rand { ... }` runs on an empty file system in
memory, a clock that starts at 0 (moved with `set_clock`) and a fixed sequence of random numbers. Every test and every
run of a property starts from a fresh `Fake`. klar/rt/fake.klar implements the same for native code: the messages and
the random numbers are identical."""

MASK = (1 << 64) - 1
SEED = 0x9E3779B97F4A7C15    # the first state of the random numbers of a test


def norm(path):
    """The absolute form of a path in the fake file system: relative paths start at `/`, `.` and `..` resolved."""
    parts = []
    for seg in path.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if parts:
                parts.pop()
            continue
        parts.append(seg)
    return "/" + "/".join(parts)


def parent(n):
    return n.rsplit("/", 1)[0] or "/"


class Fake:
    def __init__(self):
        self.files = {}          # absolute path -> content (bytes)
        self.dirs = {"/"}
        self.clock = 0           # nanoseconds
        self.rand = SEED

    # ---- fs ---------------------------------------------------------------------------------------
    def read_bytes(self, p):
        n = norm(p)
        if n in self.files:
            return True, self.files[n]
        return False, f"cannot read '{p}': " + ("Is a directory" if n in self.dirs else "No such file or directory")

    def read_file(self, p):
        good, v = self.read_bytes(p)
        if not good:
            return good, v
        try:
            return True, v.decode("utf-8")
        except UnicodeDecodeError:
            return False, f"cannot read '{p}': not valid UTF-8 text"

    def write_file(self, p, content):
        return self.write_bytes(p, content.encode("utf-8"))

    def write_bytes(self, p, content):
        n = norm(p)
        if n in self.dirs:
            return False, f"cannot write '{p}': Is a directory"
        up = parent(n)
        if up not in self.dirs:
            return False, f"cannot write '{p}': " + ("Not a directory" if self.blocked(up) else
                                                    "No such file or directory")
        self.files[n] = content
        return True, None

    def blocked(self, n):
        """Whether a file stands where a directory of path n would be."""
        while n != "/":
            if n in self.files:
                return True
            n = parent(n)
        return False

    def file_exists(self, p):
        return norm(p) in self.files

    def is_dir(self, p):
        return norm(p) in self.dirs

    def list_dir(self, p):
        n = norm(p)
        if n not in self.dirs:
            return False, f"cannot list '{p}': " + ("Not a directory" if n in self.files or self.blocked(n) else
                                                   "No such file or directory")
        prefix = n if n == "/" else n + "/"
        names = {k[len(prefix):] for k in list(self.files) + list(self.dirs)
                 if k != n and k.startswith(prefix) and "/" not in k[len(prefix):]}
        return True, tuple(sorted(names))

    def make_dir(self, p):
        n = norm(p)
        if n in self.files:
            return False, f"cannot create '{p}': File exists"
        if self.blocked(n):
            return False, f"cannot create '{p}': Not a directory"
        while n not in self.dirs:
            self.dirs.add(n)
            n = parent(n)
        return True, None

    def remove_file(self, p):
        n = norm(p)
        if n in self.dirs:
            return False, f"cannot remove '{p}': Is a directory"
        if n not in self.files:
            return False, f"cannot remove '{p}': No such file or directory"
        del self.files[n]
        return True, None

    def set_executable(self, p):
        n = norm(p)
        if n in self.files or n in self.dirs:
            return True, None
        return False, f"cannot change '{p}': No such file or directory"

    # ---- time and rand ----------------------------------------------------------------------------
    def random_int(self, lo, hi):
        x = self.rand
        x ^= (x << 13) & MASK
        x ^= x >> 7
        x ^= (x << 17) & MASK
        self.rand = x
        return lo + (x >> 3) % (hi - lo + 1)
