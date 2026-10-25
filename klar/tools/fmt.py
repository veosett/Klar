"""`klar fmt`: the canonical layout of Klar code.

One layout means fewer meaningless differences in AI output and in diffs. The formatter keeps the
author's line structure and comments; it only normalizes
  * indentation: 2 spaces per open `{` / `(` / `[`, +1 for `.method` chain lines and `requires`/`ensures`;
  * spacing between tokens (binary operators, `,`, `:`, braces, unary minus);
  * blank lines: at most one in a row, none right after `{` or before `}`, one between top-level declarations;
  * trailing whitespace and the final newline.
Safety net: the token stream of the result must be identical to the input's, otherwise nothing is changed.
"""
import re

from ..diagnostics import KlarSyntaxError
from ..lexer import KEYWORDS, Lexer

TWO = ("->", "=>", "==", "!=", "<=", ">=")
BINARY = {"+", "-", "*", "/", "%", "==", "!=", "<", ">", "<=", ">=", "=", "->", "=>", "and", "or"}
OPEN, CLOSE = "([{", ")]}"
UNARY_BEFORE = {"(", "[", "{", ",", ":", "=", "=>", "->", "+", "-", "*", "/", "%", "==", "!=", "<", ">", "<=",
                ">=", "and", "or", "not", "return", "if", "while", "in", "match", "assert", "requires", "ensures"}
TOP_LEVEL = ("fn ", "type ", "enum ", "test ", "property ", "const ", "///", "use ", "module ", "pub ", "trait ",
             "impl ")


class Tok:
    __slots__ = ("kind", "text")

    def __init__(self, kind, text):
        self.kind = kind      # word | num | str | op | comment
        self.text = text


def tokenize_line(line):
    toks, i, n = [], 0, len(line)
    while i < n:
        c = line[i]
        if c in " \t\r":
            i += 1
        elif line.startswith("//", i):
            j = i
            while j > 0 and line[j - 1] in " \t":
                j -= 1
            pad = line[j:i] if toks else ""
            toks.append(Tok("comment", (pad if pad else " ") + line[i:].rstrip() if toks else line[i:].rstrip()))
            break
        elif c == '"':
            j = i + 1
            while j < n and line[j] != '"':
                j += 2 if line[j] == "\\" else 1
            toks.append(Tok("str", line[i:j + 1]))
            i = j + 1
        elif c.isdigit():
            j = i
            while j < n and (line[j].isalnum() or line[j] == "_" or
                             (line[j] == "." and j + 1 < n and line[j + 1].isdigit()) or
                             # the sign of an exponent (1e-5); not in hexadecimal (0x1e-5 is a subtraction)
                             (line[j] in "+-" and line[j - 1] in "eE" and j + 1 < n and line[j + 1].isdigit() and
                              line[i + 1:i + 2] not in ("x", "X"))):
                j += 1
            toks.append(Tok("num", line[i:j]))
            i = j
        elif c.isalpha() or c == "_":
            j = i
            while j < n and (line[j].isalnum() or line[j] == "_"):
                j += 1
            toks.append(Tok("word", line[i:j]))
            i = j
        else:
            two = line[i:i + 2]
            if two in TWO:
                toks.append(Tok("op", two))
                i += 2
            else:
                toks.append(Tok("op", c))
                i += 1
    return toks


def is_binary(t):
    return t.text in BINARY and (t.kind == "op" or t.text in ("and", "or"))


def render(toks):
    out = []
    prev = None
    unary = False             # previous token was a unary minus
    braces = []               # for each open `{`: is it an import list `use a.{x, y}`?
    for t in toks:
        if t.kind == "comment":
            out.append(t.text)
            prev = t
            continue
        if prev is None:
            sep = ""
        elif t.text == "{" and prev.text == "." and t.kind == "op":
            sep = ""
        elif prev.text == "{" and prev.kind == "op" and braces and braces[-1]:
            sep = ""
        elif t.text == "}" and t.kind == "op" and braces and braces[-1]:
            sep = ""
        else:
            sep = space_between(prev, t, unary)
        if t.kind == "op" and t.text == "{":
            braces.append(prev is not None and prev.text == ".")
        elif t.kind == "op" and t.text == "}" and braces:
            braces.pop()
        is_unary = t.text == "-" and t.kind == "op" and (prev is None or prev.text in UNARY_BEFORE)
        out.append(sep + t.text)
        unary = is_unary
        prev = t
    return "".join(out)


def space_between(p, t, after_unary):
    pt, tt = p.text, t.text
    if after_unary:
        return ""
    if tt in (")", "]", ",", ".", "?", ":") and t.kind == "op":
        return ""
    if pt in ("(", "[", ".") and p.kind == "op":
        return ""
    if tt == "-" and t.kind == "op" and pt in UNARY_BEFORE:
        return " " if pt not in ("(", "[") else ""
    if is_binary(t) or is_binary(p):
        return " "
    if tt in ("(", "[") and t.kind == "op":
        if p.kind == "str":
            return " "
        if p.kind == "word" and pt in KEYWORDS and pt not in ("fn", "true", "false") and \
                not (pt == "impl" and tt == "["):                       # `impl[T: Show] Show for List[T]`
            return " "
        return " " if pt in (",", ":", "{") or (p.kind == "op" and pt in UNARY_BEFORE) else ""
    if tt == "{" or pt == "{":
        return "" if (pt == "{" and tt == "}") else " "
    if tt == "}":
        return " "
    if pt in (",", ":"):
        return " "
    if pt == "?" and p.kind == "op":
        return " " if t.kind in ("word", "num", "str") else ""
    return " "


def format_source(src):
    lines = src.replace("\r\n", "\n").split("\n")
    out = []
    stack = []                # indentation of the line that opened each unclosed bracket
    pending_blank = False
    continued = False         # the previous code line ended with a binary operator
    for raw in lines:
        stripped = raw.strip()
        if not stripped:
            pending_blank = bool(out)
            continue
        toks = tokenize_line(stripped)
        code = [t for t in toks if t.kind != "comment"]
        # closers at the start of the line take the indentation of their opener
        k = 0
        indent = None
        while k < len(code) and code[k].kind == "op" and code[k].text in CLOSE:
            if stack:
                indent = stack.pop()
            k += 1
        top_level = not stack and indent is None
        base = None
        if indent is None:
            indent = stack[-1] + 1 if stack else 0
            first = code[0].text if code else ""
            if continued:
                base = indent          # `{` at the end of a wrapped condition belongs to the statement
                indent += 1
            elif first == "." or first in ("requires", "ensures"):
                indent += 1
        for t in code[k:]:
            if t.kind == "op" and t.text in OPEN:
                stack.append(indent if base is None else base)
            elif t.kind == "op" and t.text in CLOSE and stack:
                stack.pop()
        text = stripped if stripped.startswith("//") else render(toks)
        prev = out[-1].strip() if out else ""
        if pending_blank and prev and not prev.endswith("{") and k == 0:
            out.append("")
        elif top_level and indent == 0 and out and prev == "}" and stripped.startswith(TOP_LEVEL):
            out.append("")
        pending_blank = False
        out.append("  " * indent + text)
        continued = bool(code) and is_binary(code[-1]) and code[-1].text not in ("=>", "->")
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out) + "\n"


def token_stream(src):
    toks = Lexer(src, "fmt").run()
    # interpolated code is compared without its position: moving a line moves the code inside its strings
    return [(t.kind, t.value if t.kind != "STR" else repr([p if isinstance(p, str) else p[1] for p in t.parts]))
            for t in toks if t.kind != "NEWLINE"]


class FormatError(Exception):
    pass


def format_checked(src):
    """Formatted text; raises FormatError if the code does not lex or the formatter would change its meaning."""
    try:
        before = token_stream(src)
    except KlarSyntaxError as ex:
        raise FormatError(f"cannot format: {ex.diag.message} at {ex.diag.span.short()}")
    result = format_source(src)
    try:
        after = token_stream(result)
    except KlarSyntaxError as ex:
        raise FormatError(f"internal formatter error ({ex.diag.message}); file left unchanged")
    if before != after:
        raise FormatError("internal formatter error (token stream changed); file left unchanged")
    if re.sub(r"\s+", "", src) != re.sub(r"\s+", "", result):
        raise FormatError("internal formatter error (non-space text changed); file left unchanged")
    return result
