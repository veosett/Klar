"""Record and replay a run: `klar run --record run.json prog.klar` writes everything the program got from outside —
input, arguments, environment variables, the clock, random numbers, files read, results of the programs it ran and of
its writes — and `klar replay run.json` runs the program again on exactly that, so a failure happens again byte for
byte, without the original files, clock or network. A replay that calls something the recording does not have next is
runtime error R0017 (the program or its source changed)."""
import base64
import hashlib
import json

from .errors import KlarRuntimeError
from .values import UNIT, Variant

FORMAT = 1

# what a program learns from outside (recorded results)
INPUTS = ("read_line", "read_exact", "cli_args", "env_var", "now_ms", "now_ns", "random_int", "read_file",
          "read_bytes", "file_exists", "is_dir", "list_dir", "current_dir")
# what a program does to the outside (recorded results; a replay does not do it again)
OUTPUTS = ("write_file", "write_bytes", "make_dir", "remove_file", "set_executable", "run_command", "run_capture")
TRACED = INPUTS + OUTPUTS


def encode(v):
    if v is UNIT:
        return {"unit": True}
    if isinstance(v, (bool, int, str)) or v is None:
        return v
    if isinstance(v, float):
        return {"float": repr(v)}
    if isinstance(v, (bytes, bytearray)):
        return {"bytes": base64.b64encode(bytes(v)).decode("ascii")}
    if isinstance(v, tuple):
        return {"list": [encode(x) for x in v]}
    if isinstance(v, Variant):
        return {"variant": [v.enum, v.name], "fields": list(v.field_names), "values": [encode(x) for x in v.values]}
    raise TypeError(f"cannot record a value of type {type(v).__name__}")


def decode(j):
    if not isinstance(j, dict):
        return j
    if "unit" in j:
        return UNIT
    if "float" in j:
        return float(j["float"])
    if "bytes" in j:
        return base64.b64decode(j["bytes"])
    if "list" in j:
        return tuple(decode(x) for x in j["list"])
    if "variant" in j:
        return Variant(j["variant"][0], j["variant"][1], [decode(x) for x in j["values"]], j["fields"])
    raise ValueError(f"unknown recorded value {j!r}")


def source_hash(loaded):
    h = hashlib.sha256()
    for name in sorted(loaded.sources):
        h.update(name.encode())
        h.update(loaded.sources[name].encode())
    return h.hexdigest()[:16]


class Trace:
    """`mode`: "record" (calls the real built-in and keeps its result) or "replay" (returns the kept results)."""

    def __init__(self, mode, events=None):
        self.mode = mode
        self.events = [] if events is None else list(events)
        self.pos = 0

    def call(self, name, impl, it, a, sp):
        if self.mode == "record":
            try:
                result = impl(it, a, sp)
            except KlarRuntimeError:
                self.events.append({"fn": name, "raised": True})
                raise
            self.events.append({"fn": name, "result": encode(result)})
            return result
        if self.pos >= len(self.events):
            raise KlarRuntimeError("R0017", f"replay diverged: the program calls `{name}`, but the recording has "
                                            f"ended", sp, hint="the program or its input changed since the recording")
        ev = self.events[self.pos]
        if ev.get("fn") != name:
            raise KlarRuntimeError("R0017", f"replay diverged: the program calls `{name}`, but the recording has "
                                            f"`{ev.get('fn')}` next (event {self.pos + 1})", sp,
                                   hint="the program or its input changed since the recording")
        self.pos += 1
        if ev.get("raised"):
            return impl(it, a, sp)      # the arguments were wrong (`random_int(5, 1)`): the same error again
        return decode(ev["result"])


def traced(name, impl):
    def run(it, a, sp):
        tr = getattr(it, "trace", None)
        if tr is None:
            return impl(it, a, sp)
        return tr.call(name, impl, it, a, sp)
    run.__doc__ = impl.__doc__
    return run


class Tee:
    """A stream that writes to another one and keeps a copy."""

    def __init__(self, inner):
        self.inner = inner
        self.parts = []

    def write(self, s):
        self.parts.append(s)
        return self.inner.write(s)

    def flush(self):
        if hasattr(self.inner, "flush"):
            self.inner.flush()

    def getvalue(self):
        return "".join(self.parts)


def save(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")


def load(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if data.get("format") != FORMAT:
        raise ValueError(f"{path} is not a Klar recording (format {FORMAT})")
    return data
