"""AST nodes. Every node carries a span and a stable numeric id
(useful for AI tools that want to address a node instead of a text range)."""
from dataclasses import dataclass, fields
from typing import Any, List, Optional

from .diagnostics import Span

_counter = [0]


@dataclass(eq=False)
class Node:
    span: Span

    def __post_init__(self):
        _counter[0] += 1
        self.id = _counter[0]


# ---- type expressions -----------------------------------------------------
@dataclass(eq=False)
class TypeName(Node):
    name: str
    args: list


@dataclass(eq=False)
class FnTypeExpr(Node):
    params: list
    ret: Any


# ---- declarations ---------------------------------------------------------
@dataclass(eq=False)
class Param(Node):
    name: str
    type: Any  # TypeExpr or None (lambdas)


@dataclass(eq=False)
class FnDecl(Node):
    name: str
    name_span: Span
    type_params: List[str]
    params: List[Param]
    ret: Any
    effects: List[str]
    effects_span: Optional[Span]
    sig_end: Span          # where `uses ...` can be inserted
    requires: list
    ensures: list
    body: Any
    doc: Optional[str] = None


@dataclass(eq=False)
class FieldDecl(Node):
    name: str
    type: Any


@dataclass(eq=False)
class TypeDecl(Node):
    name: str
    type_params: List[str]
    fields: List[FieldDecl]
    doc: Optional[str] = None


@dataclass(eq=False)
class AliasDecl(Node):
    name: str
    type_params: List[str]
    target: Any
    doc: Optional[str] = None


@dataclass(eq=False)
class ConstDecl(Node):
    name: str
    name_span: Span
    type: Any
    value: Any
    doc: Optional[str] = None


@dataclass(eq=False)
class UseDecl(Node):
    path: List[str]
    items: List[str]
    item_spans: List[Span]


@dataclass(eq=False)
class PropertyDecl(Node):
    name: str
    params: List["Param"]
    body: Any


@dataclass(eq=False)
class VariantDecl(Node):
    name: str
    fields: List[FieldDecl]


@dataclass(eq=False)
class EnumDecl(Node):
    name: str
    type_params: List[str]
    variants: List[VariantDecl]
    doc: Optional[str] = None


@dataclass(eq=False)
class TestDecl(Node):
    name: str
    body: Any


@dataclass(eq=False)
class Program(Node):
    module: Optional[str]
    decls: list
    file: str = ""


# ---- statements -------------------------------------------------------------
@dataclass(eq=False)
class Block(Node):
    stmts: list


@dataclass(eq=False)
class Let(Node):
    name: str
    name_span: Span
    kw_span: Span
    type: Any
    value: Any
    mutable: bool


@dataclass(eq=False)
class Assign(Node):
    name: str
    value: Any


@dataclass(eq=False)
class Return(Node):
    value: Any


@dataclass(eq=False)
class If(Node):
    cond: Any
    then: Block
    else_: Any  # Block | If | None


@dataclass(eq=False)
class While(Node):
    cond: Any
    body: Block


@dataclass(eq=False)
class For(Node):
    var: str
    var_span: Span
    iter: Any
    body: Block


@dataclass(eq=False)
class Break(Node):
    pass


@dataclass(eq=False)
class Continue(Node):
    pass


@dataclass(eq=False)
class Assert(Node):
    cond: Any
    message: Any


@dataclass(eq=False)
class ExprStmt(Node):
    expr: Any


# ---- expressions ------------------------------------------------------------
@dataclass(eq=False)
class IntLit(Node):
    value: int


@dataclass(eq=False)
class FloatLit(Node):
    value: float


@dataclass(eq=False)
class StrLit(Node):
    parts: list  # str | expression node


@dataclass(eq=False)
class BoolLit(Node):
    value: bool


@dataclass(eq=False)
class UnitLit(Node):
    pass


@dataclass(eq=False)
class ListLit(Node):
    items: list


@dataclass(eq=False)
class MapEntry(Node):
    key: Any
    value: Any


@dataclass(eq=False)
class MapLit(Node):
    entries: List[MapEntry]


@dataclass(eq=False)
class Name(Node):
    name: str


@dataclass(eq=False)
class Unary(Node):
    op: str
    operand: Any


@dataclass(eq=False)
class Binary(Node):
    op: str
    left: Any
    right: Any


@dataclass(eq=False)
class Arg(Node):
    name: Optional[str]
    value: Any


@dataclass(eq=False)
class Call(Node):
    callee: Any
    args: List[Arg]


@dataclass(eq=False)
class MethodCall(Node):
    obj: Any
    method: str
    method_span: Span
    args: List[Arg]


@dataclass(eq=False)
class FieldAccess(Node):
    obj: Any
    name: str
    name_span: Span


@dataclass(eq=False)
class Try(Node):
    expr: Any


@dataclass(eq=False)
class FieldInit(Node):
    name: str
    value: Any


@dataclass(eq=False)
class RecordLit(Node):
    type_name: str
    fields: List[FieldInit]


@dataclass(eq=False)
class WithExpr(Node):
    base: Any
    fields: List[FieldInit]


@dataclass(eq=False)
class MatchArm(Node):
    pattern: Any
    guard: Any  # expression or None
    body: Any  # expression or Block


@dataclass(eq=False)
class Match(Node):
    subject: Any
    arms: List[MatchArm]


@dataclass(eq=False)
class Lambda(Node):
    params: List[Param]
    ret: Any
    body: Any  # expression or Block


# ---- patterns ---------------------------------------------------------------
@dataclass(eq=False)
class PWild(Node):
    pass


@dataclass(eq=False)
class PBind(Node):
    name: str


@dataclass(eq=False)
class PLit(Node):
    value: Any


@dataclass(eq=False)
class PVariant(Node):
    enum: Optional[str]   # None for Some/None/Ok/Err
    variant: str
    args: list


# ---- JSON export ------------------------------------------------------------
def to_json(n):
    if isinstance(n, Node):
        d = {"node": type(n).__name__, "id": n.id,
             "span": [n.span.line, n.span.col, n.span.end_line, n.span.end_col]}
        for f in fields(n):
            if f.name == "span" or f.name.endswith("_span") or f.name == "sig_end":
                continue
            d[f.name] = to_json(getattr(n, f.name))
        return d
    if isinstance(n, (list, tuple)):
        return [to_json(x) for x in n]
    if isinstance(n, Span):
        return [n.line, n.col, n.end_line, n.end_col]
    return n


def walk(n):
    """Yield all nodes in a subtree."""
    if isinstance(n, Node):
        yield n
        for f in fields(n):
            v = getattr(n, f.name)
            if isinstance(v, (Node, list)):
                yield from walk(v)
    elif isinstance(n, list):
        for x in n:
            yield from walk(x)
