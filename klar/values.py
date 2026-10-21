"""Runtime values. All values are immutable."""


class _Unit:
    _inst = None

    def __new__(cls):
        if cls._inst is None:
            cls._inst = super().__new__(cls)
        return cls._inst

    def __repr__(self):
        return "()"


UNIT = _Unit()


class Record:
    __slots__ = ("type_name", "fields")

    def __init__(self, type_name, fields):
        self.type_name = type_name
        self.fields = fields  # dict, never mutated after creation

    def __eq__(self, other):
        return isinstance(other, Record) and self.type_name == other.type_name and self.fields == other.fields

    def __hash__(self):
        return hash((self.type_name, tuple(self.fields.items())))


class Variant:
    __slots__ = ("enum", "name", "values", "field_names")

    def __init__(self, enum, name, values=(), field_names=()):
        self.enum = enum
        self.name = name
        self.values = tuple(values)
        self.field_names = tuple(field_names)

    def __eq__(self, other):
        return (isinstance(other, Variant) and self.enum == other.enum and self.name == other.name
                and self.values == other.values)

    def __hash__(self):
        return hash((self.enum, self.name, self.values))


def some(v):
    return Variant("Option", "Some", (v,), ("value",))


NONE = Variant("Option", "None")


def ok(v):
    return Variant("Result", "Ok", (v,), ("value",))


def err(e):
    return Variant("Result", "Err", (e,), ("error",))


class KMap:
    """Immutable map preserving insertion order."""
    __slots__ = ("d",)

    def __init__(self, d=None):
        self.d = dict(d or {})

    def __eq__(self, other):
        return isinstance(other, KMap) and self.d == other.d

    def __hash__(self):
        return hash(tuple(self.d.items()))


class Closure:
    __slots__ = ("name", "params", "body", "env", "decl", "expr_body")

    def __init__(self, name, params, body, env, decl=None, expr_body=False):
        self.name = name
        self.params = params
        self.body = body
        self.env = env
        self.decl = decl
        self.expr_body = expr_body


class Builtin:
    __slots__ = ("name", "impl", "param_names")

    def __init__(self, name, impl, param_names):
        self.name = name
        self.impl = impl
        self.param_names = param_names


def type_head(v):
    if isinstance(v, bool):
        return "Bool"
    if isinstance(v, int):
        return "Int"
    if isinstance(v, float):
        return "Float"
    if isinstance(v, str):
        return "Str"
    if isinstance(v, bytes):
        return "Bytes"
    if isinstance(v, tuple):
        return "List"
    if isinstance(v, KMap):
        return "Map"
    if isinstance(v, Record):
        return v.type_name
    if isinstance(v, Variant):
        return v.enum
    if v is UNIT:
        return "Unit"
    return "Fn"


def _quote(s):
    out = s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")
    out = out.replace("{", "\\{").replace("}", "\\}")
    return f'"{out}"'


def show(v, top=True):
    """Canonical text form. Inside containers strings are quoted (valid Klar literals)."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        r = repr(v)
        return r
    if isinstance(v, str):
        return v if top else _quote(v)
    if isinstance(v, bytes):
        return "bytes_of([" + ", ".join(str(b) for b in v) + "])"
    if v is UNIT:
        return "()"
    if isinstance(v, tuple):
        return "[" + ", ".join(show(x, False) for x in v) + "]"
    if isinstance(v, KMap):
        if not v.d:
            return "Map {}"
        return "Map { " + ", ".join(f"{show(k, False)}: {show(x, False)}" for k, x in v.d.items()) + " }"
    if isinstance(v, Record):
        inner = ", ".join(f"{k}: {show(x, False)}" for k, x in v.fields.items())
        return f"{v.type_name} {{ {inner} }}"
    if isinstance(v, Variant):
        if v.enum in ("Option", "Result"):
            if v.values:
                return f"{v.name}({show(v.values[0], False)})"
            return v.name
        if v.values:
            inner = ", ".join(f"{n}: {show(x, False)}" for n, x in zip(v.field_names, v.values))
            return f"{v.enum}.{v.name}({inner})"
        return f"{v.enum}.{v.name}"
    if isinstance(v, (Closure, Builtin)):
        return f"<fn {v.name}>"
    return repr(v)
