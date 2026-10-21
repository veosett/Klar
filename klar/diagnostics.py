"""Diagnostics: the contract between the Klar compiler and its (AI) users.

Every problem has a stable code, an exact span, an optional hint and an
optional machine-applicable fix. Diagnostics render either for humans
(with a code frame) or as JSON.
"""
from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class Span:
    file: str
    line: int
    col: int
    end_line: int
    end_col: int

    def merge(self, other: "Span") -> "Span":
        return Span(self.file, self.line, self.col, other.end_line, other.end_col)

    def to_dict(self):
        return {"file": self.file, "line": self.line, "col": self.col,
                "end_line": self.end_line, "end_col": self.end_col}

    def short(self):
        return f"{self.file}:{self.line}:{self.col}"


BUILTIN_SPAN = Span("<builtin>", 0, 0, 0, 0)


@dataclass
class Diagnostic:
    code: str
    severity: str  # "error" | "warning"
    message: str
    span: Span
    hint: Optional[str] = None
    fix: Optional[dict] = None          # {"span": Span, "text": str}
    notes: List[str] = field(default_factory=list)

    def to_dict(self):
        d = {"code": self.code, "severity": self.severity, "message": self.message,
             "span": self.span.to_dict()}
        if self.hint:
            d["hint"] = self.hint
        if self.fix:
            d["fix"] = {"safe": self.fix.get("safe", True),
                        "edits": [{"span": e["span"].to_dict(), "text": e["text"]} for e in fix_edits(self.fix)]}
        if self.notes:
            d["notes"] = list(self.notes)
        return d

    def format(self, source: Optional[str] = None) -> str:
        out = [f"{self.severity}[{self.code}]: {self.message}",
               f"  --> {self.span.short()}"]
        frame = code_frame(source, self.span)
        if frame:
            out.append(frame)
        for n in self.notes:
            out.append(f"  note: {n}")
        if self.hint:
            out.append(f"  hint: {self.hint}")
        if self.fix:
            label = "fix: " if self.fix.get("safe", True) else "maybe:"
            for e in fix_edits(self.fix):
                sp = e["span"]
                where = (f"insert at {sp.line}:{sp.col}" if (sp.line, sp.col) == (sp.end_line, sp.end_col)
                         else f"replace {sp.line}:{sp.col}-{sp.end_line}:{sp.end_col} with")
                out.append(f"  {label} {where} {e['text']!r}")
            if self.fix.get("safe", True):
                out.append("        (apply automatically with `klar fix`)")
        return "\n".join(out)


def fix_edits(fix):
    """A fix is either {"span", "text"} or {"edits": [{"span", "text"}, ...]}; optional "safe": bool."""
    if "edits" in fix:
        return fix["edits"]
    return [{"span": fix["span"], "text": fix["text"]}]


def code_frame(source: Optional[str], span: Span) -> str:
    if not source or span.line <= 0:
        return ""
    lines = source.split("\n")
    if span.line > len(lines):
        return ""
    text = lines[span.line - 1].rstrip("\r")
    num = str(span.line)
    pad = " " * len(num)
    start = max(span.col - 1, 0)
    if span.end_line == span.line:
        width = max(span.end_col - span.col, 1)
    else:
        width = max(len(text) - start, 1)
    return (f"  {pad} |\n"
            f"  {num} | {text}\n"
            f"  {pad} | {' ' * start}{'^' * width}")


class KlarSyntaxError(Exception):
    def __init__(self, diag: Diagnostic):
        super().__init__(diag.message)
        self.diag = diag


# ---------------------------------------------------------------------------
# Error catalog: `klar explain <CODE>`
# ---------------------------------------------------------------------------
CODES = {
    # lexing / parsing
    "E0001": ("unexpected character",
              "The character is not part of Klar. Many come from other languages: use `and`/`or`/`not` "
              "instead of `&&`/`||`/`!`, no `;` at line ends, strings use double quotes."),
    "E0002": ("unterminated string",
              "Strings must close on the same line. Use `\\n` for line breaks."),
    "E0003": ("unexpected token",
              "The parser expected something else here. Read the `expected ...` part of the message."),
    "E0004": ("invalid escape sequence",
              "Valid escapes: \\n \\t \\\\ \\\" \\{ \\} \\0. Use `\\{` for a literal brace in a string."),
    # declarations / names
    "E0101": ("duplicate declaration", "Each name may be declared only once in its scope."),
    "E0102": ("shadowing is forbidden",
              "Klar never lets a new variable hide an existing one. Pick a new descriptive name, "
              "or use `var` and reassign."),
    "E0103": ("naming convention", "Types and variants are PascalCase (`BankAccount`), constants UPPER_SNAKE_CASE (`MAX_USERS`)."),
    "E0104": ("unknown type", "The type is not defined. Built-ins: Int Float Bool Str Unit Never List Map Option Result."),
    "E0105": ("wrong number of type arguments", "List[T], Option[T] take 1; Map[K, V], Result[T, E] take 2."),
    # expressions
    "E0201": ("unknown name", "The name is not defined in this scope (check spelling and declaration order inside blocks)."),
    "E0202": ("type mismatch", "The value has a different type than required. Klar has no implicit conversions."),
    "E0203": ("unknown field", "The record has no such field."),
    "E0204": ("unknown method", "The type has no such method. `klar spec` lists every built-in method."),
    "E0205": ("missing return", "A function with a non-Unit result must `return` on every path."),
    "E0206": ("wrong number of arguments", "Pass exactly the declared parameters."),
    "E0207": ("assignment to immutable variable", "Declare the variable with `var` to reassign it. Record fields are never assigned: use `rec with { field: v }`."),
    "E0208": ("named arguments required",
              "Functions with 3 or more parameters must be called with named arguments: `f(a: 1, b: 2, c: 3)`."),
    "E0209": ("bad argument or field list", "Unknown, duplicate or missing named argument / record field."),
    "E0210": ("not callable", "Only functions can be called."),
    "E0211": ("invalid operands", "The operator is not defined for these types."),
    "E0212": ("invalid use of `?`",
              "`?` unwraps Option/Result and returns early on None/Err. The enclosing function must return a "
              "compatible Option/Result (with the same error type)."),
    "E0213": ("break/continue outside loop", "`break` and `continue` only work inside `while`/`for`."),
    "E0214": ("cannot infer type", "Add a type annotation, e.g. `let xs: List[Int] = []`."),
    "E0216": ("lambda captures a `var`",
              "Lambdas may capture `let` values, parameters and loop variables, but not a `var`: whether the lambda "
              "would see later changes (and whether it could change the variable) is a classic source of bugs. "
              "Take a snapshot (`let n_now = n`) or accumulate with `fold` / a `for` loop."),
    "E0215": ("values are not ordered", "`sort`, `min`, `max` (and the keys of `sort_by`/`min_by`/`max_by`) need Int, "
              "Float or Str. Sort records by a field: `xs.sort_by(fn(p) => p.age)`."),
    # traits
    "E0220": ("trait not implemented",
              "A generic function with a bound (`fn f[T: Shape](x: T)`) can only be called with a type that has "
              "`impl Shape for ThatType`, or with a type parameter that carries the same bound."),
    "E0221": ("impl does not match its trait",
              "An `impl Trait for Type` must define every trait method without a default, only methods of the trait, "
              "with the trait's parameter names and types (`Self` = the type), the same return type and no extra "
              "effects. `klar fix` inserts `todo(...)` stubs for missing methods."),
    "E0222": ("impl in the wrong place or twice",
              "There is at most one `impl Trait for Type` per program, written in the trait's module or in the type's "
              "module (impls for Int/Float/Bool/Str live with the trait). Every module then sees the same methods."),
    "E0223": ("cannot infer the type of a bounded parameter",
              "The type must be known to choose the implementation: annotate the value (`let xs: List[Circle] = []`)."),
    "E0224": ("a trait is not a type",
              "Klar has no trait objects: write a generic function `fn f[T: Shape](x: T)` for one kind of value at a "
              "time; for a list of different kinds, declare an `enum` with one variant per kind and implement the "
              "trait for the enum (each method is one `match`)."),
    # match
    "E0301": ("non-exhaustive match", "Cover every variant or add a catch-all `_ => ...` arm."),
    "E0302": ("invalid pattern", "The pattern does not fit the matched type, or the variant does not exist."),
    "W0303": ("unreachable match arm", "An earlier catch-all arm already matches everything."),
    # effects / values
    "E0401": ("missing effect", "Functions must declare effects they use: `fn f() uses io { ... }`. Contracts are pure; tests may only use `io`."),
    "E0402": ("unhandled Result", "A `Result` may carry an error and must be handled with `?`, `match`, or discarded explicitly with `let _ = ...`."),
    "E0403": ("unknown effect", "Known effects: io, time, rand, fs, net."),
    "E0405": ("discarded immutable update",
              "Values are immutable. Methods like `push`, `set`, `concat`, `with` return a NEW value; "
              "assign it: `xs = xs.push(1)` (requires `var xs`)."),
    "W0401": ("unused value", "The expression's value is thrown away. Use `let _ = ...` if intended."),
    "W0402": ("unused variable", "Remove it or prefix its name with `_`."),
    "W0104": ("value names should be snake_case", "Write `total_count`, not `totalCount`."),
    # program
    "E0501": ("no main function", "`klar run` needs `fn main()` (optionally `-> Result[Unit, E]`) — use `uses io` to print."),
    "E0502": ("invalid main signature", "`main` takes no parameters and returns Unit or Result[Unit, E]."),
    "W0404": ("unfinished code", "`todo(...)` marks code that still has to be written; it fails at runtime with R0012."),
    # modules / constants / properties
    "E0601": ("module not found", "`use a.b.{x}` loads the file `a/b.klar` next to the importing file."),
    "E0602": ("circular import", "Modules may not import each other in a cycle. Move shared code into a third module."),
    "E0603": ("unknown import", "The module does not declare that name. Imports are explicit: `use m.{name}`."),
    "E0604": ("constant used before declaration", "A constant may only use constants declared above it."),
    "E0605": ("property input not generatable", "Property inputs must be data types (no functions or generic parameters)."),
    # compile-time safety (klar/safety.py)
    "E0701": ("divisor may be zero",
              "Int `/` and `%` are only allowed when the compiler can see the divisor is not zero: a non-zero "
              "literal or constant, a value checked by `if b != 0`, `while b > 0`, `assert b != 0`, an early "
              "`if b == 0 { return ... }`, `match b { 0 => ..., _ => a / b }`, `requires b != 0`, "
              "`if xs.is_empty() { return ... }` (then `xs.len()` > 0), a callee's `ensures result > 0`, or a `var` "
              "that starts positive and only grows. Float division is rejected only for a literal 0.0."),
    "E0702": ("unconditional recursion",
              "Every path through the function calls itself before it can return, so it would recurse until "
              "the stack overflows. Add a base case that returns without the recursive call."),
    "E0703": ("precondition violated at compile time",
              "The call passes constant arguments for which a `requires` clause of the callee is false."),
    "E0704": ("invalid constant argument to built-in",
              "The argument is outside the built-in's domain (negative `Int.pow` exponent, `sqrt` of a negative "
              "number, `ln` of a non-positive number, `chunks(0)`, ...), so the call could only fail."),
    "E0705": ("index always out of bounds",
              "Indexes go from 0 to `len() - 1`: `xs.get(xs.len())` and negative indexes never find an element. "
              "Use `xs.last()` for the last element."),
    # runtime
    "R0001": ("division by zero", "Only possible for Float division by a value computed at run time "
              "(Int division by zero is rejected at compile time: E0701). Check the divisor before dividing."),
    "R0002": ("precondition violated", "A `requires` clause was false on entry. The caller passed invalid arguments."),
    "R0003": ("postcondition violated", "An `ensures` clause was false on return. The function body is wrong."),
    "R0004": ("fail() called", "The program called `fail(message)`."),
    "R0005": ("assertion failed", "An `assert` was false; for comparisons both sides are shown."),
    "R0006": ("stack overflow", "Recursion went deeper than 10000 calls (recursion without any base case is "
              "already rejected at compile time: E0702). Use a loop or reduce the depth."),
    "R0007": ("main returned Err", "`main` returned `Err(...)`."),
    "R0008": ("`?` failed inside a test", "A `?` in a test hit Err/None, which fails the test."),
    "R0009": ("invalid argument to built-in", "A built-in received a value outside its domain (e.g. negative sqrt)."),
    "R0010": ("property falsified", "A `property` failed for some generated input. The report shows the minimal "
              "(shrunk) counterexample and the seed to reproduce it."),
    "R0011": ("index out of bounds", "`List.set`/`insert`/`remove_at` got an index outside the list."),
    "R0012": ("reached todo()", "The program executed a `todo(...)` placeholder."),
}


def explain(code: str) -> str:
    code = code.upper()
    if code not in CODES:
        return f"unknown code {code}. Known: " + ", ".join(sorted(CODES))
    title, text = CODES[code]
    return f"{code}: {title}\n\n{text}"
