"""Lexer for Klar.

* Newline terminates a statement, except inside ( ) and [ ] and except
  when the next line starts with `.` (method chains).
* Strings support interpolation: "Hello {name}!"; `\\{` is a literal brace.
* Operators borrowed from other languages (&&, ||, !, ;) produce targeted errors.
"""
from dataclasses import dataclass
from typing import Any, List, Optional

from .diagnostics import Diagnostic, KlarSyntaxError, Span

KEYWORDS = {
    "module", "use", "fn", "type", "enum", "let", "var", "return", "if", "else",
    "while", "for", "in", "break", "continue", "match", "test", "assert",
    "requires", "ensures", "uses", "and", "or", "not", "true", "false", "with",
    "const", "property",
}

TWO_CHAR = {"->", "=>", "==", "!=", "<=", ">="}
ONE_CHAR = set("+-*/%<>=()[]{},:.?")

FOREIGN = {
    "&&": "Klar uses the word `and`",
    "||": "Klar uses the word `or`",
    "++": "no increment operator: write `i = i + 1` (with `var i`)",
    "--": "no decrement operator: write `i = i - 1`; comments start with `//`",
    "+=": "no compound assignment: write `x = x + 1`",
    "-=": "no compound assignment: write `x = x - 1`",
    "*=": "no compound assignment: write `x = x * 2`",
    "::": "use `.` for paths: `Color.Red`",
    "!": "Klar uses the word `not`",
    ";": "statements end at the end of a line; remove the `;`",
    "'": "strings use double quotes: \"text\"",
    "&": "no references or bitwise ops in Klar; use `and` for logic",
    "|": "use `or` for logic; lambdas are written `fn(x) => x + 1`",
    "#": "comments start with `//`",
    "@": "Klar has no decorators/annotations",
    "`": "strings use double quotes; interpolation is \"{expr}\"",
}


@dataclass
class Token:
    kind: str          # INT FLOAT STR IDENT KW OP NEWLINE DOC EOF
    value: Any
    span: Span
    parts: Optional[list] = None   # for STR: list of str | ("expr", text, line, col)

    def describe(self) -> str:
        if self.kind == "NEWLINE":
            return "end of line"
        if self.kind == "EOF":
            return "end of file"
        if self.kind == "STR":
            return "a string"
        return f"`{self.value}`"


class Lexer:
    def __init__(self, src: str, file: str, line: int = 1, col: int = 1):
        self.src = src
        self.file = file
        self.i = 0
        self.line = line
        self.col = col
        self.toks: List[Token] = []
        self.stack: List[str] = []

    # -- helpers ----------------------------------------------------------
    def ch(self, k: int = 0) -> str:
        j = self.i + k
        return self.src[j] if j < len(self.src) else ""

    def adv(self) -> str:
        c = self.src[self.i]
        self.i += 1
        if c == "\n":
            self.line += 1
            self.col = 1
        else:
            self.col += 1
        return c

    def error(self, code, msg, line, col, hint=None, width=1, replacement=None):
        span = Span(self.file, line, col, line, col + width)
        fix = {"span": span, "text": replacement} if replacement is not None else None
        raise KlarSyntaxError(Diagnostic(code, "error", msg, span, hint, fix))

    def add(self, kind, value, sl, sc, parts=None):
        self.toks.append(Token(kind, value, Span(self.file, sl, sc, self.line, self.col), parts))

    def statement_level(self) -> bool:
        return not self.stack or self.stack[-1] == "{"

    def next_line_continues(self) -> bool:
        """True if the next significant character is a `.` (method chain)."""
        j = self.i
        src = self.src
        while j < len(src):
            c = src[j]
            if c in " \t\r\n":
                j += 1
            elif c == "/" and j + 1 < len(src) and src[j + 1] == "/":
                while j < len(src) and src[j] != "\n":
                    j += 1
            else:
                break
        return j < len(src) and src[j] == "." and not (j + 1 < len(src) and src[j + 1] == ".")

    # -- main loop --------------------------------------------------------
    def run(self) -> List[Token]:
        while self.i < len(self.src):
            c = self.ch()
            sl, sc = self.line, self.col
            if c in " \t\r":
                self.adv()
            elif c == "\n":
                self.adv()
                if (self.statement_level() and self.toks and self.toks[-1].kind != "NEWLINE"
                        and not self.next_line_continues()):
                    self.add("NEWLINE", "\n", sl, sc)
            elif c == "/" and self.ch(1) == "/":
                is_doc = self.ch(2) == "/" and self.ch(3) != "/"
                text = []
                while self.i < len(self.src) and self.ch() != "\n":
                    text.append(self.adv())
                if is_doc and not self.stack:
                    self.add("DOC", "".join(text)[3:], sl, sc)  # raw text after ///
            elif c.isdigit():
                self.number(sl, sc)
            elif c == '"':
                self.string(sl, sc)
            elif c.isalpha() or c == "_":
                buf = []
                while self.ch() and (self.ch().isalnum() or self.ch() == "_"):
                    buf.append(self.adv())
                word = "".join(buf)
                self.add("KW" if word in KEYWORDS else "IDENT", word, sl, sc)
            else:
                self.operator(c, sl, sc)
        if self.toks and self.toks[-1].kind != "NEWLINE":
            self.add("NEWLINE", "\n", self.line, self.col)
        self.add("EOF", None, self.line, self.col)
        return self.toks

    def number(self, sl, sc):
        buf = []
        while self.ch().isdigit() or self.ch() == "_":
            buf.append(self.adv())
        is_float = False
        if self.ch() == "." and self.ch(1).isdigit():
            is_float = True
            buf.append(self.adv())
            while self.ch().isdigit() or self.ch() == "_":
                buf.append(self.adv())
        text = "".join(buf).replace("_", "")
        if self.ch().isalpha() or self.ch() == "_":
            self.error("E0001", f"invalid number literal `{''.join(buf)}{self.ch()}`", sl, sc,
                       "numbers cannot be followed by letters (no suffixes like 10u or 1f)")
        if is_float:
            self.add("FLOAT", float(text), sl, sc)
        else:
            self.add("INT", int(text), sl, sc)

    def string(self, sl, sc):
        self.adv()  # opening quote
        parts: list = []
        buf: List[str] = []
        escapes = {"n": "\n", "t": "\t", "\\": "\\", '"': '"', "{": "{", "}": "}", "0": "\0", "r": "\r"}
        while True:
            if self.i >= len(self.src) or self.ch() == "\n":
                self.error("E0002", "unterminated string", sl, sc,
                           'close the string with `"` on the same line; use `\\n` for line breaks')
            c = self.ch()
            if c == '"':
                self.adv()
                break
            if c == "\\":
                el, ec = self.line, self.col
                self.adv()
                e = self.ch()
                if e not in escapes:
                    self.error("E0004", f"invalid escape `\\{e}`", el, ec,
                               "valid escapes: \\n \\t \\\\ \\\" \\{ \\} \\0", width=2)
                self.adv()
                buf.append(escapes[e])
            elif c == "{":
                if buf:
                    parts.append("".join(buf))
                    buf = []
                self.adv()
                el, ec = self.line, self.col
                depth = 1
                text = []
                while True:
                    if self.i >= len(self.src) or self.ch() == "\n":
                        self.error("E0002", "unterminated interpolation `{...}` in string", el, ec - 1,
                                   "close it with `}`, or write `\\{` for a literal brace")
                    c2 = self.ch()
                    if c2 == "{":
                        depth += 1
                    elif c2 == "}":
                        depth -= 1
                        if depth == 0:
                            self.adv()
                            break
                    elif c2 == '"':
                        self.error("E0003", "string literals are not allowed inside `{...}` interpolation",
                                   self.line, self.col, "compute the value into a variable first")
                    text.append(self.adv())
                if not "".join(text).strip():
                    self.error("E0003", "empty interpolation `{}`", el, ec - 1, "write `\\{\\}` for literal braces")
                parts.append(("expr", "".join(text), el, ec))
            else:
                buf.append(self.adv())
        if buf:
            parts.append("".join(buf))
        value = "".join(p for p in parts if isinstance(p, str))
        self.add("STR", value, sl, sc, parts)

    def operator(self, c, sl, sc):
        two = c + self.ch(1)
        if two in FOREIGN and two not in TWO_CHAR:
            self.error("E0001", f"`{two}` is not a Klar operator", sl, sc, FOREIGN[two], width=2,
                       replacement={"&&": "and", "||": "or", "::": "."}.get(two))
        if two in TWO_CHAR:
            self.adv()
            self.adv()
            self.add("OP", two, sl, sc)
            return
        if c in ONE_CHAR:
            self.adv()
            if c in "([{":
                self.stack.append(c)
            elif c in ")]}":
                if self.stack:
                    self.stack.pop()
            self.add("OP", c, sl, sc)
            return
        hint = FOREIGN.get(c)
        replacement = {";": "", "!": "not "}.get(c)
        if c == ";" and self.ch(1) not in ("\n", "\r", "", " ", "\t", "/"):
            replacement = None   # `a; b` on one line needs a line break, not a deletion
        self.error("E0001", f"unexpected character `{c}`", sl, sc, hint, replacement=replacement)


def tokenize(src: str, file: str, line: int = 1, col: int = 1) -> List[Token]:
    return Lexer(src, file, line, col).run()
