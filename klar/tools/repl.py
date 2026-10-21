"""`klar repl` — an interactive session.

Every input is type-checked together with everything entered before (as one Klar function body plus the
declarations), so a REPL session obeys exactly the rules of a program: no shadowing, no implicit conversions,
effects allowed: io, time, rand, fs. Only the NEW statements run — earlier `print`s and `read_line`s are not
repeated — and their variables live on in the session.

    klar> let xs = [3, 1, 2]
    klar> xs.sort()
    [1, 2, 3] : List[Int]
    klar> fn double(n: Int) -> Int {
    ....>   return n * 2
    ....> }
    klar> xs.map(double)
    [6, 2, 4] : List[Int]
"""
import os
import re
import sys

from .. import nodes as N
from ..diagnostics import KlarSyntaxError
from ..errors import KlarRuntimeError
from ..interpreter import Env, Interpreter, run_with_big_stack
from ..loader import load_source
from ..parser import parse
from ..types import prune, show
from ..values import UNIT, show as show_value

ENTRY = "klar_repl_entry"
VALUE = "klar_repl_value"
DECL_START = re.compile(r"^(pub\s+)?(fn|type|enum|const|trait|impl|test|property)\b")
HELP = """Enter Klar statements, expressions or declarations (fn, type, enum, const, trait, impl, use).
  :type <expr>    show the type without running
  :doc <name>     signature and examples of a built-in or of your function
  :load <file>    add the declarations of a .klar file (its `main` is not run)
  :defs           the declarations of this session
  :reset          forget everything
  :quit           leave (also Ctrl-D)"""


def balance(text):
    """How many brackets are still open (strings and comments ignored)."""
    depth, in_str, k = 0, False, 0
    while k < len(text):
        c = text[k]
        if in_str:
            if c == "\\":
                k += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "/" and text[k + 1:k + 2] == "/":
            nl = text.find("\n", k)
            k = len(text) if nl < 0 else nl
            continue
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        k += 1
    return depth


def needs_more(text):
    stripped = text.rstrip()
    if not stripped:
        return False
    if balance(text) > 0:
        return True
    return stripped.endswith(("+", "-", "*", "/", "%", "=", "and", "or", "not", ",", "->", "=>", "==", "!=",
                              "<", ">", "<=", ">=")) and not stripped.endswith("()")


class Repl:
    def __init__(self, cwd=None, out=None, inp=None):
        self.cwd = os.path.abspath(cwd or os.getcwd())
        self.out = out or sys.stdout
        self.inp = inp or sys.stdin
        self.reset()

    def reset(self):
        self.uses = []        # `use` lines
        self.decls = []       # declaration sources
        self.stmts = []       # statement sources (checked every time, run once)
        self.vars = {}        # values of the session's variables

    # ---- program assembly -------------------------------------------------------------------------------
    def source(self, extra_stmts=(), extra_decls=(), extra_uses=()):
        uses = list(self.uses) + list(extra_uses)
        decls = list(self.decls) + list(extra_decls)
        head = "".join(u + "\n" for u in uses) + "".join(d.rstrip("\n") + "\n\n" for d in decls)
        body_lines = [ln for s in list(self.stmts) + list(extra_stmts) for ln in s.split("\n")]
        start = head.count("\n") + 2 + sum(s.count("\n") + 1 for s in self.stmts)
        body = "".join("  " + ln + "\n" for ln in body_lines)
        return head + f"fn {ENTRY}() uses io, time, rand, fs {{\n{body}}}\n", start

    def check(self, src):
        loaded = load_source(src, "repl.klar", root=self.cwd)
        errors = [d for d in loaded.diags if d.severity == "error"]
        return loaded, errors

    def show_errors(self, errors, src, start, kind, multiline=False):
        for d in errors[:5]:
            where = ""
            if d.span.file == "repl.klar" and kind == "stmt" and d.span.line >= start and multiline:
                where = f" (line {d.span.line - start + 1} of the input)"
            elif d.span.file not in ("repl.klar", ""):
                where = f" ({d.span.short()})"
            msg = re.sub(r"\(first declared at repl\.klar:\d+:\d+\)", "(in an earlier input)", d.message)
            msg = re.sub(r"repl\.klar:\d+:\d+", "an earlier input", msg)
            self.say(f"error[{d.code}]: {msg}{where}")
            if d.hint:
                self.say(f"  hint: {d.hint}")

    def say(self, text):
        print(text, file=self.out)

    # ---- one input ----------------------------------------------------------------------------------
    def feed(self, text):
        """Process one complete input; returns False when the session should end."""
        text = text.strip("\n")
        if not text.strip():
            return True
        if text.startswith(":"):
            return self.command(text)
        if text.lstrip().startswith("use "):
            return self.add_decl(text.strip(), is_use=True)
        if DECL_START.match(text.lstrip()):
            return self.add_decl(text)
        return self.run_input(text)

    def add_decl(self, text, is_use=False):
        extra_uses, extra_decls = ([text], []) if is_use else ([], [text])
        src, start = self.source(extra_decls=extra_decls, extra_uses=extra_uses)
        try:
            errors = self.check(src)[1]
        except KlarSyntaxError as ex:
            errors = [ex.diag]
        if errors:
            self.show_errors(errors, src, start, "decl")
            return True
        if is_use:
            self.uses.append(text)
        else:
            # a new definition of the same name replaces the old one
            name = self.decl_name(text)
            self.decls = [d for d in self.decls if self.decl_name(d) != name or name is None] + [text]
            if name:
                self.say(f"defined {name}")
        return True

    @staticmethod
    def decl_name(text):
        m = re.match(r"\s*(?:pub\s+)?(?:fn|type|enum|const|trait)\s+([A-Za-z_][A-Za-z0-9_]*)", text)
        return m.group(1) if m else None

    def is_expression(self, text):
        try:
            prog = parse(f"fn f() {{\n  let {VALUE} = {text}\n}}\n", "x.klar")
        except KlarSyntaxError:
            return False
        return len(prog.decls[0].body.stmts) == 1

    def run_input(self, text, type_only=False):
        expr = self.is_expression(text)
        new = [f"let {VALUE} = {text}"] if expr else [text]
        src, start = self.source(extra_stmts=new)
        try:
            loaded, errors = self.check(src)
        except KlarSyntaxError as ex:
            self.show_errors([ex.diag], src, start, "stmt", "\n" in text)
            return True
        if errors:
            self.show_errors(errors, src, start, "stmt", "\n" in text)
            return True
        entry = next(d for d in loaded.program.decls if isinstance(d, N.FnDecl) and d.name == ENTRY)
        count = len(parse("fn f() {\n" + "\n".join(new) + "\n}\n", "x.klar").decls[0].body.stmts)
        fresh = entry.body.stmts[len(entry.body.stmts) - count:]
        if expr:
            let = fresh[-1]
            typ = show(prune(let.value.kt)) if getattr(let.value, "kt", None) is not None else "?"
            if type_only:
                self.say(typ)
                return True
        interp = Interpreter(loaded, out=self.out, err_stream=self.out)
        try:
            def go():
                interp.initialize()
                env = Env(interp.main_env, self.vars)
                interp.stack.append((ENTRY, entry.span))
                for s in fresh:
                    interp.exec(s, env)
            run_with_big_stack(go)
        except KlarRuntimeError as ex:
            d = ex.to_diag()
            self.say(f"runtime error[{d.code}]: {d.message}")
            for n in d.notes:
                if not n.startswith("call stack"):
                    self.say(f"  note: {n}")
            if d.hint:
                self.say(f"  hint: {d.hint}")
            self.vars.pop(VALUE, None)
            return True
        except SystemExit:
            raise
        if expr:
            value = self.vars.pop(VALUE, None)
            if value is not UNIT:
                self.say(f"{show_value(value, False)} : {typ}")
        else:
            self.stmts.append(text)
        return True

    def command(self, text):
        cmd, _, arg = text.partition(" ")
        arg = arg.strip()
        if cmd in (":q", ":quit", ":exit"):
            return False
        if cmd in (":h", ":help", ":?"):
            self.say(HELP)
        elif cmd in (":t", ":type"):
            self.run_input(arg, type_only=True)
        elif cmd == ":doc":
            from .inspect import doc_lookup, doc_text
            loaded = None
            if self.decls:
                try:
                    loaded = self.check(self.source()[0])[0]
                except KlarSyntaxError:
                    loaded = None
            self.say(doc_text(doc_lookup(arg, loaded), limit=6))
        elif cmd == ":load":
            path = os.path.join(self.cwd, arg)
            try:
                with open(path, encoding="utf-8") as f:
                    src = f.read()
            except OSError as ex:
                self.say(f"cannot read {arg}: {ex.strerror}")
                return True
            for d in split_decls(src):
                if d.lstrip().startswith("use "):
                    self.add_decl(d.strip(), is_use=True)
                elif not re.match(r"\s*fn\s+main\s*\(", d) and DECL_START.match(d.lstrip()):
                    self.add_decl(d)
        elif cmd == ":defs":
            for u in self.uses:
                self.say(u)
            for d in self.decls:
                self.say(d.split("\n")[0] + (" ..." if "\n" in d else ""))
            for name, v in self.vars.items():
                self.say(f"{name} = {show_value(v, False)}")
        elif cmd == ":reset":
            self.reset()
            self.say("session cleared")
        else:
            self.say(f"unknown command {cmd} (:help lists them)")
        return True

    # ---- the loop ---------------------------------------------------------------------------------------
    def loop(self):
        from .. import __version__
        interactive = self.inp.isatty() if hasattr(self.inp, "isatty") else False
        if interactive:
            try:
                import readline  # noqa: F401  (line editing and history where available)
            except ImportError:
                pass
            self.say(f"Klar {__version__} — :help for commands, :quit to leave")
        buf = []
        while True:
            prompt = "....> " if buf else "klar> "
            try:
                line = input(prompt) if interactive else self.inp.readline()
            except EOFError:
                break
            except KeyboardInterrupt:
                self.say("")
                buf = []
                continue
            if not interactive:
                if line == "":
                    break
                line = line.rstrip("\n")
            buf.append(line)
            text = "\n".join(buf)
            if needs_more(text):
                continue
            buf = []
            try:
                if not self.feed(text):
                    break
            except Exception as ex:   # the session survives internal errors
                self.say(f"internal error: {type(ex).__name__}: {ex}")
        return 0


def split_decls(src):
    """Top-level declarations of a source file as separate texts (by bracket balance)."""
    out, cur = [], []
    for line in src.split("\n"):
        if not cur and (not line.strip() or line.strip().startswith("//")):
            continue
        cur.append(line)
        text = "\n".join(cur)
        if balance(text) == 0 and not needs_more(text) and not line.rstrip().endswith("{"):
            nxt_needed = re.match(r"\s*(fn|requires|ensures)\b", line) and not line.rstrip().endswith("}")
            if not nxt_needed:
                out.append(text)
                cur = []
    if cur:
        out.append("\n".join(cur))
    return out


def cmd_repl(args):
    return Repl().loop()


def register(sub):
    p = sub.add_parser("repl", help="interactive session: statements, expressions and declarations")
    p.set_defaults(fn=cmd_repl)
