"""Native build driver: Klar source -> standalone executable (no C compiler, no libc, no Python at run time)."""
import hashlib
import os
import sys

from .emit import Emitter
from .opt import inline_calls
from .link import Image
from .lower import NativeUnsupported, lower_program
from ..loader import load_path

CACHE_DIR = os.path.join(os.path.expanduser("~"), ".klar-cache")


def host_target():
    """The native target for this machine, or None when it is not x86-64 Linux/Windows."""
    import platform
    if platform.machine().lower() not in ("x86_64", "amd64"):
        return None
    if os.name == "nt":
        return "windows"
    if sys.platform.startswith("linux"):
        return "linux"
    return None


RT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "rt")
NATIVE_DIR = os.path.dirname(os.path.abspath(__file__))


def cache_key(loaded, target):
    """Hash of everything the executable depends on: user modules, runtime and compiler sources."""
    from .. import __version__
    h = hashlib.sha256()
    h.update(f"{__version__}|{target}".encode())
    for name in sorted(loaded.sources):
        h.update(name.encode())
        h.update(loaded.sources[name].encode())
    for d in (RT_DIR, NATIVE_DIR, os.path.dirname(NATIVE_DIR)):
        for fname in sorted(os.listdir(d)):
            if fname.endswith((".klar", ".py")):
                with open(os.path.join(d, fname), "rb") as f:
                    h.update(f.read())
    return h.hexdigest()[:24]


def cached_build(path, loaded_user, target=None):
    """Build into ~/.klar-cache unless an identical executable is already there."""
    target = target or host_target()
    key = cache_key(loaded_user, target)
    os.makedirs(CACHE_DIR, exist_ok=True)
    exe = os.path.join(CACHE_DIR, key + (".exe" if target == "windows" else ""))
    if not os.path.exists(exe):
        tmp = exe + ".tmp"
        build(path, out=tmp, target=target)
        os.replace(tmp, exe)
    return exe


def build(path, out=None, target=None, loaded=None, tests=None):
    """Returns (output_path, loaded). Raises NativeUnsupported for programs the backend cannot compile yet."""
    target = target or host_target()
    loaded = loaded or load_path(path, with_runtime=True)
    if loaded.has_errors():
        errs = [d for d in loaded.diags if d.severity == "error"]
        raise SystemExit("\n".join(d.format(loaded.sources.get(d.span.file)) for d in errs))
    img = Image()
    prog, rt = lower_program(loaded, img, tests)
    em = Emitter(img, target, rt)
    em.os_layer()
    inline_calls(prog.fns)
    for fn in prog.fns:
        em.function(fn)
    em.finish()
    if out is None:
        stem = os.path.splitext(os.path.basename(path))[0]
        out = os.path.join(os.path.dirname(os.path.abspath(path)), stem + (".exe" if target == "windows" else ""))
    if target == "windows":
        img.write_pe(out)
    else:
        img.write_elf(out)
        os.chmod(out, 0o755)
    if os.environ.get("KLAR_MAP"):
        base = 0x401000 if target == "linux" else 0x140001000
        with open(out + ".map", "w") as f:
            for name, off in sorted(img.code_labels.items(), key=lambda kv: kv[1]):
                if not name.startswith("."):
                    f.write(f"{base + off:x} {name}\n")
    return out, loaded
