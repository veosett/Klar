"""Klar standard library.

Signatures are written in Klar itself and parsed by the same parser, so the
type checker, the docs (`klar spec`) and the runtime share one source of truth.
"""
import math
import random
import re
import time

from .errors import KlarExit, KlarRuntimeError
from .values import (UNIT, KMap, NONE, Record, err, ok, show, some)

GLOBALS = {}   # name -> (signature, impl)
METHODS = {}   # owner -> name -> (signature, impl)


def _name_of(sig):
    return re.match(r"fn\s+(\w+)", sig).group(1)


def glob(sig):
    def deco(f):
        GLOBALS[_name_of(sig)] = (sig, f)
        return f
    return deco


def method(owner, sig):
    def deco(f):
        METHODS.setdefault(owner, {})[_name_of(sig)] = (sig, f)
        return f
    return deco


def rt_error(code, msg, span):
    return KlarRuntimeError(code, msg, span)


# ---------------------------------------------------------------------------
# Global functions
# ---------------------------------------------------------------------------
@glob("fn print[T](value: T) -> Unit uses io")
def _print(it, a, sp):
    it.out.write(show(a[0], True) + "\n")
    return UNIT


@glob("fn read_line() -> Option[Str] uses io")
def _read_line(it, a, sp):
    line = it.inp.readline()
    if line == "":
        return NONE
    return some(line.rstrip("\n").rstrip("\r"))


@glob("fn fail(message: Str) -> Never")
def _fail(it, a, sp):
    raise KlarRuntimeError("R0004", f"fail: {a[0]}", sp)


@glob("fn range(start: Int, end: Int) -> List[Int]")
def _range(it, a, sp):
    return tuple(range(a[0], a[1]))


@glob("fn now_ms() -> Int uses time")
def _now(it, a, sp):
    return int(time.time() * 1000)


@glob("fn now_ns() -> Int uses time")
def _now_ns(it, a, sp):
    return time.perf_counter_ns()


@glob("fn random_int(min: Int, max: Int) -> Int uses rand")
def _rand(it, a, sp):
    if a[0] > a[1]:
        raise rt_error("R0009", f"random_int: min ({a[0]}) > max ({a[1]})", sp)
    return random.randint(a[0], a[1])


@glob("fn dbg[T](value: T) -> T uses io")
def _dbg(it, a, sp):
    text = it.src(sp)
    if text.startswith("dbg(") and text.endswith(")"):
        text = text[4:-1]
    it.err.write(f"[dbg {sp.short()}] {text} = {show(a[0], False)}\n")
    return a[0]


@glob("fn todo(what: Str) -> Never")
def _todo(it, a, sp):
    raise KlarRuntimeError("R0012", f"reached unfinished code: todo(\"{a[0]}\")", sp)


@glob("fn read_file(path: Str) -> Result[Str, Str] uses fs")
def _read_file(it, a, sp):
    try:
        with open(a[0], encoding="utf-8") as f:
            return ok(f.read())
    except OSError as ex:
        return err(f"cannot read '{a[0]}': {ex.strerror}")
    except UnicodeDecodeError:
        return err(f"cannot read '{a[0]}': not valid UTF-8 text")


@glob("fn write_file(path: Str, content: Str) -> Result[Unit, Str] uses fs")
def _write_file(it, a, sp):
    try:
        with open(a[0], "w", encoding="utf-8") as f:
            f.write(a[1])
        return ok(UNIT)
    except OSError as ex:
        return err(f"cannot write '{a[0]}': {ex.strerror}")


@glob("fn file_exists(path: Str) -> Bool uses fs")
def _file_exists(it, a, sp):
    import os
    return os.path.isfile(a[0])


@glob("fn exit(code: Int) -> Never uses io")
def _exit(it, a, sp):
    raise KlarExit(max(0, min(255, a[0])), sp)


@glob("fn env_var(name: Str) -> Option[Str] uses io")
def _env_var(it, a, sp):
    import os
    v = os.environ.get(a[0])
    return NONE if v is None else some(v)


@glob("fn cli_args() -> List[Str] uses io")
def _cli_args(it, a, sp):
    return tuple(it.cli_args)


@glob("fn Some[T](value: T) -> Option[T]")
def _some(it, a, sp):
    return some(a[0])


@glob("fn Ok[T, E](value: T) -> Result[T, E]")
def _ok(it, a, sp):
    return ok(a[0])


@glob("fn Err[T, E](error: E) -> Result[T, E]")
def _err(it, a, sp):
    return err(a[0])


# ---------------------------------------------------------------------------
# Int / Float
# ---------------------------------------------------------------------------
@method("Int", "fn to_float(self: Int) -> Float")
def _(it, a, sp): return float(a[0])


@method("Int", "fn abs(self: Int) -> Int")
def _(it, a, sp): return abs(a[0])


@method("Int", "fn min(self: Int, other: Int) -> Int")
def _(it, a, sp): return min(a[0], a[1])


@method("Int", "fn max(self: Int, other: Int) -> Int")
def _(it, a, sp): return max(a[0], a[1])


@method("Int", "fn clamp(self: Int, low: Int, high: Int) -> Int")
def _(it, a, sp): return max(a[1], min(a[0], a[2]))


@method("Int", "fn is_even(self: Int) -> Bool")
def _(it, a, sp): return a[0] % 2 == 0


@method("Int", "fn sign(self: Int) -> Int")
def _(it, a, sp): return (a[0] > 0) - (a[0] < 0)


MAX_SHIFT = 1 << 20


@method("Int", "fn bit_and(self: Int, other: Int) -> Int")
def _(it, a, sp): return a[0] & a[1]


@method("Int", "fn bit_or(self: Int, other: Int) -> Int")
def _(it, a, sp): return a[0] | a[1]


@method("Int", "fn bit_xor(self: Int, other: Int) -> Int")
def _(it, a, sp): return a[0] ^ a[1]


@method("Int", "fn bit_not(self: Int) -> Int")
def _(it, a, sp): return ~a[0]


def _shift_amount(n, what, sp):
    if n < 0 or n > MAX_SHIFT:
        raise rt_error("R0009", f"Int.{what}: shift must be between 0 and {MAX_SHIFT}, got {n}", sp)
    return n


@method("Int", "fn shift_left(self: Int, bits: Int) -> Int")
def _(it, a, sp): return a[0] << _shift_amount(a[1], "shift_left", sp)


@method("Int", "fn shift_right(self: Int, bits: Int) -> Int")
def _(it, a, sp): return a[0] >> _shift_amount(a[1], "shift_right", sp)


@method("Int", "fn to_char(self: Int) -> Option[Str]")
def _(it, a, sp):
    c = a[0]
    if 0 <= c <= 0x10FFFF and not 0xD800 <= c <= 0xDFFF:
        return some(chr(c))
    return NONE


@method("Int", "fn pow(self: Int, exp: Int) -> Int")
def _(it, a, sp):
    if a[1] < 0:
        raise rt_error("R0009", f"Int.pow: negative exponent {a[1]} (use Float for fractions)", sp)
    return a[0] ** a[1]


@method("Float", "fn to_int(self: Float) -> Int")
def _(it, a, sp): return int(a[0])


@method("Float", "fn round(self: Float) -> Int")
def _(it, a, sp): return int(math.floor(a[0] + 0.5))


@method("Float", "fn floor(self: Float) -> Int")
def _(it, a, sp): return int(math.floor(a[0]))


@method("Float", "fn ceil(self: Float) -> Int")
def _(it, a, sp): return int(math.ceil(a[0]))


@method("Float", "fn abs(self: Float) -> Float")
def _(it, a, sp): return abs(a[0])


@method("Float", "fn sqrt(self: Float) -> Float")
def _(it, a, sp):
    if a[0] < 0:
        raise rt_error("R0009", f"Float.sqrt of negative number {a[0]}", sp)
    return math.sqrt(a[0])


@method("Float", "fn min(self: Float, other: Float) -> Float")
def _(it, a, sp): return min(a[0], a[1])


@method("Float", "fn max(self: Float, other: Float) -> Float")
def _(it, a, sp): return max(a[0], a[1])


@method("Float", "fn round_to(self: Float, digits: Int) -> Float")
def _(it, a, sp): return round(a[0], a[1])


@method("Float", "fn pow(self: Float, exp: Float) -> Float")
def _(it, a, sp):
    try:
        r = a[0] ** a[1]
    except (OverflowError, ZeroDivisionError) as ex:
        raise rt_error("R0009", f"Float.pow({a[0]}, {a[1]}): {ex}", sp)
    if isinstance(r, complex):
        raise rt_error("R0009", f"Float.pow: negative base {a[0]} with fractional exponent {a[1]}", sp)
    return float(r)


@method("Float", "fn fixed(self: Float, digits: Int) -> Str")
def _(it, a, sp):
    if a[1] < 0:
        raise rt_error("R0009", f"Float.fixed: negative digits {a[1]}", sp)
    return f"{a[0]:.{a[1]}f}"


@method("Float", "fn sin(self: Float) -> Float")
def _(it, a, sp): return math.sin(a[0])


@method("Float", "fn cos(self: Float) -> Float")
def _(it, a, sp): return math.cos(a[0])


@method("Float", "fn ln(self: Float) -> Float")
def _(it, a, sp):
    if a[0] <= 0:
        raise rt_error("R0009", f"Float.ln of non-positive number {a[0]}", sp)
    return math.log(a[0])


@method("Float", "fn exp(self: Float) -> Float")
def _(it, a, sp):
    try:
        return math.exp(a[0])
    except OverflowError:
        raise rt_error("R0009", f"Float.exp({a[0]}) overflows", sp)


# ---------------------------------------------------------------------------
# Str
# ---------------------------------------------------------------------------
@method("Str", "fn len(self: Str) -> Int")
def _(it, a, sp): return len(a[0])


@method("Str", "fn is_empty(self: Str) -> Bool")
def _(it, a, sp): return len(a[0]) == 0


@method("Str", "fn upper(self: Str) -> Str")
def _(it, a, sp): return a[0].upper()


@method("Str", "fn lower(self: Str) -> Str")
def _(it, a, sp): return a[0].lower()


@method("Str", "fn trim(self: Str) -> Str")
def _(it, a, sp): return a[0].strip()


@method("Str", "fn split(self: Str, sep: Str) -> List[Str]")
def _(it, a, sp):
    if a[1] == "":
        return tuple(a[0])
    return tuple(a[0].split(a[1]))


@method("Str", "fn contains(self: Str, part: Str) -> Bool")
def _(it, a, sp): return a[1] in a[0]


@method("Str", "fn starts_with(self: Str, prefix: Str) -> Bool")
def _(it, a, sp): return a[0].startswith(a[1])


@method("Str", "fn ends_with(self: Str, suffix: Str) -> Bool")
def _(it, a, sp): return a[0].endswith(a[1])


@method("Str", "fn replace(self: Str, old: Str, new: Str) -> Str")
def _(it, a, sp): return a[0].replace(a[1], a[2])


@method("Str", "fn index_of(self: Str, part: Str) -> Option[Int]")
def _(it, a, sp):
    i = a[0].find(a[1])
    return NONE if i < 0 else some(i)


@method("Str", "fn slice(self: Str, start: Int, end: Int) -> Str")
def _(it, a, sp): return a[0][max(a[1], 0):max(a[2], 0)]


@method("Str", "fn chars(self: Str) -> List[Str]")
def _(it, a, sp): return tuple(a[0])


@method("Str", "fn to_bytes(self: Str) -> Bytes")
def _(it, a, sp): return a[0].encode("utf-8")


# ---- Bytes: an immutable sequence of bytes (0..255) ------------------------------------------------
def _byte(b, what, sp):
    if not 0 <= b <= 255:
        raise rt_error("R0009", f"{what}: {b} is not a byte (0..255)", sp)
    return b


@glob("fn bytes_of(xs: List[Int]) -> Bytes")
def _bytes_of(it, a, sp): return bytes(_byte(b, "bytes_of", sp) for b in a[0])


@glob("fn read_bytes(path: Str) -> Result[Bytes, Str] uses fs")
def _read_bytes(it, a, sp):
    try:
        with open(a[0], "rb") as f:
            return ok(f.read())
    except OSError as ex:
        return err(f"cannot read '{a[0]}': {ex.strerror}")


@glob("fn write_bytes(path: Str, data: Bytes) -> Result[Unit, Str] uses fs")
def _write_bytes(it, a, sp):
    try:
        with open(a[0], "wb") as f:
            f.write(a[1])
        return ok(UNIT)
    except OSError as ex:
        return err(f"cannot write '{a[0]}': {ex.strerror}")


@method("Bytes", "fn len(self: Bytes) -> Int")
def _(it, a, sp): return len(a[0])


@method("Bytes", "fn is_empty(self: Bytes) -> Bool")
def _(it, a, sp): return len(a[0]) == 0


@method("Bytes", "fn get(self: Bytes, index: Int) -> Option[Int]")
def _(it, a, sp): return some(a[0][a[1]]) if 0 <= a[1] < len(a[0]) else NONE


@method("Bytes", "fn get_or(self: Bytes, index: Int, default: Int) -> Int")
def _(it, a, sp): return a[0][a[1]] if 0 <= a[1] < len(a[0]) else a[2]


@method("Bytes", "fn slice(self: Bytes, start: Int, end: Int) -> Bytes")
def _(it, a, sp): return a[0][max(a[1], 0):max(a[2], 0)]


@method("Bytes", "fn concat(self: Bytes, other: Bytes) -> Bytes")
def _(it, a, sp): return a[0] + a[1]


@method("Bytes", "fn push(self: Bytes, byte: Int) -> Bytes")
def _(it, a, sp): return a[0] + bytes((_byte(a[1], "Bytes.push", sp),))


@method("Bytes", "fn push_le(self: Bytes, value: Int, size: Int) -> Bytes")
def _(it, a, sp):
    data, v, n = a
    if n not in (1, 2, 4, 8):
        raise rt_error("R0009", f"Bytes.push_le: size must be 1, 2, 4 or 8, got {n}", sp)
    if not -(1 << (8 * n - 1)) <= v < (1 << (8 * n)):
        raise rt_error("R0009", f"Bytes.push_le: {v} does not fit in {n} byte(s)", sp)
    return data + (v & ((1 << (8 * n)) - 1)).to_bytes(n, "little")


@method("Bytes", "fn set(self: Bytes, index: Int, byte: Int) -> Bytes")
def _(it, a, sp):
    data, i, b = a
    if not 0 <= i < len(data):
        raise rt_error("R0011", f"Bytes.set: index {i} out of bounds for length {len(data)}", sp)
    return data[:i] + bytes((_byte(b, "Bytes.set", sp),)) + data[i + 1:]


@method("Bytes", "fn to_list(self: Bytes) -> List[Int]")
def _(it, a, sp): return tuple(a[0])


@method("Bytes", "fn decode(self: Bytes) -> Result[Str, Str]")
def _(it, a, sp):
    try:
        return ok(a[0].decode("utf-8"))
    except UnicodeDecodeError as ex:
        return err(f"not valid UTF-8 at byte {ex.start}")


@method("Bytes", "fn hex(self: Bytes) -> Str")
def _(it, a, sp): return a[0].hex()


@method("Str", "fn codes(self: Str) -> List[Int]")
def _(it, a, sp): return tuple(ord(c) for c in a[0])


@method("Str", "fn repeat(self: Str, times: Int) -> Str")
def _(it, a, sp): return a[0] * max(a[1], 0)


@method("Str", "fn to_int(self: Str) -> Option[Int]")
def _(it, a, sp):
    s = a[0].strip()
    if re.fullmatch(r"[+-]?\d+", s):
        return some(int(s))
    return NONE


@method("Str", "fn to_float(self: Str) -> Option[Float]")
def _(it, a, sp):
    s = a[0].strip()
    if re.fullmatch(r"[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?", s):
        return some(float(s))
    return NONE


@method("Str", "fn lines(self: Str) -> List[Str]")
def _(it, a, sp): return tuple(a[0].splitlines())


def _fill(f, sp):
    if len(f) != 1:
        raise rt_error("R0009", f"fill must be exactly one character, got {show(f, False)}", sp)
    return f


@method("Str", "fn pad_left(self: Str, width: Int, fill: Str) -> Str")
def _(it, a, sp): return a[0].rjust(a[1], _fill(a[2], sp))


@method("Str", "fn pad_right(self: Str, width: Int, fill: Str) -> Str")
def _(it, a, sp): return a[0].ljust(a[1], _fill(a[2], sp))


@method("Str", "fn trim_start(self: Str) -> Str")
def _(it, a, sp): return a[0].lstrip()


@method("Str", "fn trim_end(self: Str) -> Str")
def _(it, a, sp): return a[0].rstrip()


@method("Str", "fn count(self: Str, part: Str) -> Int")
def _(it, a, sp):
    if a[1] == "":
        raise rt_error("R0009", "Str.count: empty part", sp)
    return a[0].count(a[1])


@method("Str", "fn reverse(self: Str) -> Str")
def _(it, a, sp): return a[0][::-1]


@method("Str", "fn is_numeric(self: Str) -> Bool")
def _(it, a, sp): return a[0] != "" and a[0].isdigit()


# ---------------------------------------------------------------------------
# List[T]  (immutable; every "modifying" method returns a new list)
# ---------------------------------------------------------------------------
def _call(it, f, args, sp):
    return it.call_value(f, args, sp)


@method("List", "fn len[T](self: List[T]) -> Int")
def _(it, a, sp): return len(a[0])


@method("List", "fn is_empty[T](self: List[T]) -> Bool")
def _(it, a, sp): return len(a[0]) == 0


@method("List", "fn get[T](self: List[T], index: Int) -> Option[T]")
def _(it, a, sp):
    xs, i = a
    return some(xs[i]) if 0 <= i < len(xs) else NONE


@method("List", "fn get_or[T](self: List[T], index: Int, default: T) -> T")
def _(it, a, sp):
    xs, i, d = a
    return xs[i] if 0 <= i < len(xs) else d


@method("List", "fn first[T](self: List[T]) -> Option[T]")
def _(it, a, sp): return some(a[0][0]) if a[0] else NONE


@method("List", "fn last[T](self: List[T]) -> Option[T]")
def _(it, a, sp): return some(a[0][-1]) if a[0] else NONE


@method("List", "fn push[T](self: List[T], item: T) -> List[T]")
def _(it, a, sp): return a[0] + (a[1],)


@method("List", "fn set[T](self: List[T], index: Int, item: T) -> List[T]")
def _(it, a, sp):
    xs, i, v = a
    if not 0 <= i < len(xs):
        raise rt_error("R0011", f"List.set: index {i} out of bounds for length {len(xs)}", sp)
    return xs[:i] + (v,) + xs[i + 1:]


@method("List", "fn concat[T](self: List[T], other: List[T]) -> List[T]")
def _(it, a, sp): return a[0] + a[1]


@method("List", "fn map[T, U](self: List[T], f: fn(T) -> U) -> List[U]")
def _(it, a, sp): return tuple(_call(it, a[1], [x], sp) for x in a[0])


@method("List", "fn filter[T](self: List[T], keep: fn(T) -> Bool) -> List[T]")
def _(it, a, sp): return tuple(x for x in a[0] if _call(it, a[1], [x], sp))


@method("List", "fn fold[T, A](self: List[T], init: A, f: fn(A, T) -> A) -> A")
def _(it, a, sp):
    acc = a[1]
    for x in a[0]:
        acc = _call(it, a[2], [acc, x], sp)
    return acc


@method("List", "fn any[T](self: List[T], pred: fn(T) -> Bool) -> Bool")
def _(it, a, sp): return any(_call(it, a[1], [x], sp) for x in a[0])


@method("List", "fn all[T](self: List[T], pred: fn(T) -> Bool) -> Bool")
def _(it, a, sp): return all(_call(it, a[1], [x], sp) for x in a[0])


@method("List", "fn find[T](self: List[T], pred: fn(T) -> Bool) -> Option[T]")
def _(it, a, sp):
    for x in a[0]:
        if _call(it, a[1], [x], sp):
            return some(x)
    return NONE


@method("List", "fn count[T](self: List[T], pred: fn(T) -> Bool) -> Int")
def _(it, a, sp): return sum(1 for x in a[0] if _call(it, a[1], [x], sp))


@method("List", "fn contains[T](self: List[T], item: T) -> Bool")
def _(it, a, sp): return a[1] in a[0]


@method("List", "fn index_of[T](self: List[T], item: T) -> Option[Int]")
def _(it, a, sp):
    for i, x in enumerate(a[0]):
        if x == a[1]:
            return some(i)
    return NONE


@method("List", "fn reverse[T](self: List[T]) -> List[T]")
def _(it, a, sp): return tuple(reversed(a[0]))


def _sorted(xs, key, sp):
    try:
        return tuple(sorted(xs, key=key))
    except TypeError:
        raise rt_error("R0009", "sort: values are not comparable (only Int, Float, Str can be sorted)", sp)


@method("List", "fn sort[T](self: List[T]) -> List[T]")
def _(it, a, sp): return _sorted(a[0], None, sp)


@method("List", "fn sort_by[T, K](self: List[T], key: fn(T) -> K) -> List[T]")
def _(it, a, sp): return _sorted(a[0], lambda x: _call(it, a[1], [x], sp), sp)


@method("List", "fn slice[T](self: List[T], start: Int, end: Int) -> List[T]")
def _(it, a, sp): return a[0][max(a[1], 0):max(a[2], 0)]


@method("List", "fn take[T](self: List[T], n: Int) -> List[T]")
def _(it, a, sp): return a[0][:max(a[1], 0)]


@method("List", "fn drop[T](self: List[T], n: Int) -> List[T]")
def _(it, a, sp): return a[0][max(a[1], 0):]


@method("List", "fn join(self: List[Str], sep: Str) -> Str")
def _(it, a, sp): return a[1].join(a[0])


@method("List", "fn sum(self: List[Int]) -> Int")
def _(it, a, sp): return sum(a[0])


@method("List", "fn sum_float(self: List[Float]) -> Float")
def _(it, a, sp): return float(math.fsum(a[0]))


@method("List", "fn enumerate[T](self: List[T]) -> List[Indexed[T]]")
def _(it, a, sp): return tuple(Record("Indexed", {"index": i, "value": x}) for i, x in enumerate(a[0]))


@method("List", "fn zip[T, U](self: List[T], other: List[U]) -> List[Pair[T, U]]")
def _(it, a, sp): return tuple(Record("Pair", {"first": x, "second": y}) for x, y in zip(a[0], a[1]))


@method("List", "fn flat_map[T, U](self: List[T], f: fn(T) -> List[U]) -> List[U]")
def _(it, a, sp): return tuple(y for x in a[0] for y in _call(it, a[1], [x], sp))


@method("List", "fn flatten[T](self: List[List[T]]) -> List[T]")
def _(it, a, sp): return tuple(y for x in a[0] for y in x)


@method("List", "fn unique[T](self: List[T]) -> List[T]")
def _(it, a, sp):
    seen, out = set(), []
    for x in a[0]:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return tuple(out)


@method("List", "fn partition[T](self: List[T], pred: fn(T) -> Bool) -> Pair[List[T], List[T]]")
def _(it, a, sp):
    yes, no = [], []
    for x in a[0]:
        (yes if _call(it, a[1], [x], sp) else no).append(x)
    return Record("Pair", {"first": tuple(yes), "second": tuple(no)})


@method("List", "fn group_by[T, K](self: List[T], key: fn(T) -> K) -> Map[K, List[T]]")
def _(it, a, sp):
    d = {}
    for x in a[0]:
        d.setdefault(_call(it, a[1], [x], sp), []).append(x)
    return KMap({k: tuple(v) for k, v in d.items()})


@method("List", "fn chunks[T](self: List[T], size: Int) -> List[List[T]]")
def _(it, a, sp):
    if a[1] <= 0:
        raise rt_error("R0009", f"List.chunks: size must be positive, got {a[1]}", sp)
    return tuple(a[0][i:i + a[1]] for i in range(0, len(a[0]), a[1]))


def _extreme(xs, key, pick, sp):
    if not xs:
        return NONE
    try:
        return some(pick(xs, key=key) if key else pick(xs))
    except TypeError:
        raise rt_error("R0009", "values are not comparable (only Int, Float, Str)", sp)


@method("List", "fn min[T](self: List[T]) -> Option[T]")
def _(it, a, sp): return _extreme(a[0], None, min, sp)


@method("List", "fn max[T](self: List[T]) -> Option[T]")
def _(it, a, sp): return _extreme(a[0], None, max, sp)


@method("List", "fn min_by[T, K](self: List[T], key: fn(T) -> K) -> Option[T]")
def _(it, a, sp): return _extreme(a[0], lambda x: _call(it, a[1], [x], sp), min, sp)


@method("List", "fn max_by[T, K](self: List[T], key: fn(T) -> K) -> Option[T]")
def _(it, a, sp): return _extreme(a[0], lambda x: _call(it, a[1], [x], sp), max, sp)


@method("List", "fn insert[T](self: List[T], index: Int, item: T) -> List[T]")
def _(it, a, sp):
    xs, i, v = a
    if not 0 <= i <= len(xs):
        raise rt_error("R0011", f"List.insert: index {i} out of bounds for length {len(xs)}", sp)
    return xs[:i] + (v,) + xs[i:]


@method("List", "fn remove_at[T](self: List[T], index: Int) -> List[T]")
def _(it, a, sp):
    xs, i = a
    if not 0 <= i < len(xs):
        raise rt_error("R0011", f"List.remove_at: index {i} out of bounds for length {len(xs)}", sp)
    return xs[:i] + xs[i + 1:]


# ---------------------------------------------------------------------------
# Map[K, V]  (immutable, insertion-ordered)
# ---------------------------------------------------------------------------
@method("Map", "fn len[K, V](self: Map[K, V]) -> Int")
def _(it, a, sp): return len(a[0].d)


@method("Map", "fn is_empty[K, V](self: Map[K, V]) -> Bool")
def _(it, a, sp): return not a[0].d


@method("Map", "fn get[K, V](self: Map[K, V], key: K) -> Option[V]")
def _(it, a, sp): return some(a[0].d[a[1]]) if a[1] in a[0].d else NONE


@method("Map", "fn has[K, V](self: Map[K, V], key: K) -> Bool")
def _(it, a, sp): return a[1] in a[0].d


@method("Map", "fn set[K, V](self: Map[K, V], key: K, value: V) -> Map[K, V]")
def _(it, a, sp):
    d = dict(a[0].d)
    d[a[1]] = a[2]
    return KMap(d)


@method("Map", "fn remove[K, V](self: Map[K, V], key: K) -> Map[K, V]")
def _(it, a, sp):
    d = dict(a[0].d)
    d.pop(a[1], None)
    return KMap(d)


@method("Map", "fn keys[K, V](self: Map[K, V]) -> List[K]")
def _(it, a, sp): return tuple(a[0].d.keys())


@method("Map", "fn values[K, V](self: Map[K, V]) -> List[V]")
def _(it, a, sp): return tuple(a[0].d.values())


@method("Map", "fn entries[K, V](self: Map[K, V]) -> List[Entry[K, V]]")
def _(it, a, sp): return tuple(Record("Entry", {"key": k, "value": v}) for k, v in a[0].d.items())


@method("Map", "fn map_values[K, V, W](self: Map[K, V], f: fn(V) -> W) -> Map[K, W]")
def _(it, a, sp): return KMap({k: _call(it, a[1], [v], sp) for k, v in a[0].d.items()})


@method("Map", "fn update[K, V](self: Map[K, V], key: K, default: V, f: fn(V) -> V) -> Map[K, V]")
def _(it, a, sp):
    d = dict(a[0].d)
    d[a[1]] = _call(it, a[3], [d.get(a[1], a[2])], sp)
    return KMap(d)


@method("Map", "fn filter[K, V](self: Map[K, V], keep: fn(K, V) -> Bool) -> Map[K, V]")
def _(it, a, sp): return KMap({k: v for k, v in a[0].d.items() if _call(it, a[1], [k, v], sp)})


@method("Map", "fn merge[K, V](self: Map[K, V], other: Map[K, V]) -> Map[K, V]")
def _(it, a, sp):
    d = dict(a[0].d)
    d.update(a[1].d)
    return KMap(d)


# ---------------------------------------------------------------------------
# Option[T] / Result[T, E]
# ---------------------------------------------------------------------------
@method("Option", "fn is_some[T](self: Option[T]) -> Bool")
def _(it, a, sp): return a[0].name == "Some"


@method("Option", "fn is_none[T](self: Option[T]) -> Bool")
def _(it, a, sp): return a[0].name == "None"


@method("Option", "fn unwrap_or[T](self: Option[T], default: T) -> T")
def _(it, a, sp): return a[0].values[0] if a[0].name == "Some" else a[1]


@method("Option", "fn map[T, U](self: Option[T], f: fn(T) -> U) -> Option[U]")
def _(it, a, sp): return some(_call(it, a[1], [a[0].values[0]], sp)) if a[0].name == "Some" else NONE


@method("Option", "fn and_then[T, U](self: Option[T], f: fn(T) -> Option[U]) -> Option[U]")
def _(it, a, sp): return _call(it, a[1], [a[0].values[0]], sp) if a[0].name == "Some" else NONE


@method("Option", "fn ok_or[T, E](self: Option[T], error: E) -> Result[T, E]")
def _(it, a, sp): return ok(a[0].values[0]) if a[0].name == "Some" else err(a[1])


@method("Result", "fn is_ok[T, E](self: Result[T, E]) -> Bool")
def _(it, a, sp): return a[0].name == "Ok"


@method("Result", "fn is_err[T, E](self: Result[T, E]) -> Bool")
def _(it, a, sp): return a[0].name == "Err"


@method("Result", "fn unwrap_or[T, E](self: Result[T, E], default: T) -> T")
def _(it, a, sp): return a[0].values[0] if a[0].name == "Ok" else a[1]


@method("Result", "fn map[T, E, U](self: Result[T, E], f: fn(T) -> U) -> Result[U, E]")
def _(it, a, sp): return ok(_call(it, a[1], [a[0].values[0]], sp)) if a[0].name == "Ok" else a[0]


@method("Result", "fn map_err[T, E, F](self: Result[T, E], f: fn(E) -> F) -> Result[T, F]")
def _(it, a, sp): return err(_call(it, a[1], [a[0].values[0]], sp)) if a[0].name == "Err" else a[0]


@method("Result", "fn ok[T, E](self: Result[T, E]) -> Option[T]")
def _(it, a, sp): return some(a[0].values[0]) if a[0].name == "Ok" else NONE


# ---------------------------------------------------------------------------
# Parsed signature cache
# ---------------------------------------------------------------------------
_PARSED = {}


def parsed(sig):
    if sig not in _PARSED:
        from .parser import parse_signature
        _PARSED[sig] = parse_signature(sig)
    return _PARSED[sig]


def param_names(sig, skip_self=False):
    decl = parsed(sig)
    names = [p.name for p in decl.params]
    return names[1:] if skip_self else names


# Habits from other languages -> the Klar name. Used for "did you mean" hints.
FOREIGN_METHODS = {
    "length": "len", "size": "len", "count": "len",
    "append": "push", "add": "push", "push_back": "push", "put": "set",
    "toString": "to_str", "to_string": "to_str", "str": "to_str", "toStr": "to_str",
    "toUpperCase": "upper", "uppercase": "upper", "to_upper": "upper", "toLowerCase": "lower",
    "lowercase": "lower", "to_lower": "lower", "strip": "trim",
    "includes": "contains", "has_key": "has", "containsKey": "has", "contains_key": "has",
    "indexOf": "index_of", "find_index": "index_of",
    "reduce": "fold", "inject": "fold", "sorted": "sort", "reversed": "reverse",
    "forEach": None, "for_each": None, "each": None,
    "unwrap": None, "expect": None, "get_or": "unwrap_or", "getOrElse": "unwrap_or",
    "unwrap_or_default": "unwrap_or", "or_else": "unwrap_or",
    "flatMap": "and_then", "flat_map": "and_then",
    "parse": "to_int", "parseInt": "to_int", "toInt": "to_int",
    "substring": "slice", "substr": "slice", "startsWith": "starts_with", "endsWith": "ends_with",
    "isEmpty": "is_empty", "empty": "is_empty", "delete": "remove", "pop": None,
    "splitlines": "lines", "ljust": "pad_right", "rjust": "pad_left", "padStart": "pad_left",
    "padEnd": "pad_right", "lstrip": "trim_start", "rstrip": "trim_end", "items": "entries",
    "distinct": "unique", "dedup": "unique", "groupBy": "group_by", "chunked": "chunks",
    "concat_map": "flat_map", "toFixed": "fixed", "powf": "pow", "log": "ln",
}

FOREIGN_NOTES = {
    "forEach": "Klar has no forEach: use `for x in xs { ... }`",
    "for_each": "Klar has no for_each: use `for x in xs { ... }`",
    "each": "use `for x in xs { ... }`",
    "unwrap": "Klar has no `unwrap`: use `?`, `match`, or `.unwrap_or(default)`",
    "expect": "Klar has no `expect`: use `?`, `match`, or `.unwrap_or(default)`",
    "pop": "lists are immutable: use `.last()` and `.take(xs.len() - 1)`",
}
