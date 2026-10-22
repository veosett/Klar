"""`klar lsp` — a Language Server Protocol server over stdin/stdout (no dependencies).

Every feature reuses the compiler: the loader + checker produce diagnostics and typed ASTs, `klar fmt`
formats, the outline gives symbols, `name_occurrences` gives references. Klar forbids shadowing, so a name
inside a function means one thing, and a top-level name means one thing in the whole program: definition,
references and rename are exact without an index.

Supported: diagnostics (with quick fixes as code actions), hover (types, signatures, docs), go to definition,
references, rename, completion (names, `.` members, keywords), signature help, document symbols, formatting.
"""
import argparse
import json
import os
import re
import sys
import traceback
from urllib.parse import quote, unquote, urlparse

from .. import nodes as N
from ..builtins import GLOBALS, METHODS
from ..diagnostics import fix_edits
from ..loader import load_source
from ..types import TCon, TParam, head, prune, show
from .inspect import DECL_KINDS, find_word_span, name_occurrences, sig_text

KEYWORDS = ["fn", "let", "var", "if", "else", "while", "for", "in", "return", "match", "type", "enum", "trait",
            "impl", "pub", "use", "const", "test", "property", "assert", "requires", "ensures", "uses", "break",
            "continue", "and", "or", "not", "true", "false", "with", "None", "Some", "Ok", "Err"]
SNIPPETS = {
    "fn": "fn ${1:name}(${2:x}: ${3:Int}) -> ${4:Int} {\n  return $0\n}",
    "main": "fn main() uses io {\n  $0\n}",
    "test": "test \"${1:what}\" {\n  assert $0\n}",
    "match": "match ${1:value} {\n  ${2:pattern} => $0,\n}",
    "trait": "trait ${1:Name} {\n  fn ${2:method}(self) -> ${3:Str}\n}",
    "impl": "impl ${1:Trait} for ${2:Type} {\n  $0\n}",
}
# LSP enums
SEV = {"error": 1, "warning": 2}
CK = {"method": 2, "function": 3, "field": 5, "variable": 6, "class": 7, "interface": 8, "keyword": 14,
      "snippet": 15, "enum": 13, "member": 20, "constant": 21, "struct": 22}
SK = {"fn": 12, "type": 23, "enum": 10, "alias": 26, "const": 14, "trait": 11, "impl": 5, "test": 24,
      "property": 24, "method": 6}


# ---- paths, positions ----------------------------------------------------------------------------------
def uri_to_path(uri):
    p = unquote(urlparse(uri).path)
    if re.match(r"^/[A-Za-z]:", p):           # file:///c:/x on Windows
        p = p[1:]
    return os.path.abspath(p)


def path_to_uri(path):
    path = os.path.abspath(path).replace("\\", "/")
    if not path.startswith("/"):
        path = "/" + path
    return "file://" + quote(path)


def utf16_len(s):
    return sum(2 if ord(c) > 0xFFFF else 1 for c in s)


def to_lsp_pos(lines, line, col):
    """Klar 1-based line / character column -> LSP 0-based line / UTF-16 column."""
    text = lines[line - 1] if 0 < line <= len(lines) else ""
    return {"line": max(line - 1, 0), "character": utf16_len(text[:max(col - 1, 0)])}


def from_lsp_pos(lines, pos):
    """LSP position -> Klar (line, col), both 1-based."""
    line = pos["line"] + 1
    text = lines[line - 1] if 0 < line <= len(lines) else ""
    units, col = 0, 0
    for ch in text:
        if units >= pos["character"]:
            break
        units += 2 if ord(ch) > 0xFFFF else 1
        col += 1
    return line, col + 1


def to_range(lines, span):
    return {"start": to_lsp_pos(lines, span.line, span.col), "end": to_lsp_pos(lines, span.end_line, span.end_col)}


def contains(span, line, col):
    if span is None or span.line <= 0:
        return False
    if (line, col) < (span.line, span.col):
        return False
    return (line, col) <= (span.end_line, span.end_col)


def span_size(span):
    return (span.end_line - span.line) * 10000 + (span.end_col - span.col)


# ---- one analysed program --------------------------------------------------------------------------------
class Analysis:
    def __init__(self, path, text, overlay):
        self.path = path
        self.text = text
        self.lines = text.split("\n")
        self.loaded = load_source(text, os.path.basename(path), root=os.path.dirname(path), overlay=overlay)
        self.main = self.loaded.main
        self.ok = self.main is not None and self.main.program is not None
        self.modules = {m.name: m for m in self.loaded.modules}
        self.by_display = {m.display: m for m in self.loaded.modules}

    def lines_of(self, display):
        return self.loaded.sources.get(display, "").split("\n")

    def path_of(self, display):
        m = self.by_display.get(display)
        return m.path if m is not None else os.path.join(os.path.dirname(self.path), display)

    def location(self, span):
        if span is None or span.file in ("", "<builtin>") or span.line <= 0:
            return None
        if span.file.startswith("std/") or span.file == "prelude.klar":
            m = self.by_display.get(span.file)
            if m is None:
                return None
            path = m.path
        else:
            path = self.path_of(span.file)
        return {"uri": path_to_uri(path), "range": to_range(self.lines_of(span.file), span)}

    # ---- finding the node under the cursor -----------------------------------------------------------
    def node_at(self, line, col):
        """(node, the span of its name/word, enclosing top-level declaration) for the innermost named thing."""
        if not self.ok:
            return None, None, None
        best = None
        for d in self.main.program.decls:
            if not contains(d.span, line, col) and not (isinstance(d, N.FnDecl) and d.owner_kind):
                continue
            for n in N.walk(d):
                sp = self.name_span(n)
                if sp is not None and contains(sp, line, col):
                    if best is None or span_size(sp) < span_size(best[1]):
                        best = (n, sp, d)
            if isinstance(d, N.FnDecl):
                for items in d.bounds.values():
                    for tname, sp in items:
                        if contains(sp, line, col):
                            best = (("bound", tname), sp, d)
            if isinstance(d, N.ImplDecl) and contains(d.trait_span, line, col):
                best = (("bound", d.trait), d.trait_span, d)
        return best if best else (None, None, None)

    def name_span(self, n):
        lines = self.lines
        if isinstance(n, N.Name):
            return n.span
        if isinstance(n, N.MethodCall):
            return n.method_span
        if isinstance(n, N.FieldAccess):
            return n.name_span
        if isinstance(n, (N.FnDecl, N.ConstDecl, N.Let)):
            return n.name_span
        if isinstance(n, N.TraitDecl):
            return n.name_span
        if isinstance(n, N.For):
            return n.var_span
        if isinstance(n, N.PBind):
            return n.span
        if isinstance(n, N.Param):
            return find_word_span(lines, n.span, n.name)
        if isinstance(n, N.TypeName):
            return find_word_span(lines, n.span, n.name)
        if isinstance(n, N.RecordLit):
            return find_word_span(lines, n.span, n.type_name)
        if isinstance(n, (N.TypeDecl, N.EnumDecl, N.AliasDecl)):
            return find_word_span(lines, n.span, n.name)
        if isinstance(n, N.PVariant) and n.enum:
            return find_word_span(lines, n.span, n.variant)
        return None

    # ---- what a name refers to ------------------------------------------------------------------------
    def local_decl(self, top, name):
        """The binding of a local name inside one top-level declaration (unique: no shadowing)."""
        for n in N.walk(top):
            if isinstance(n, N.Let) and n.name == name:
                return n.name_span
            if isinstance(n, N.Param) and n.name == name:
                return find_word_span(self.lines, n.span, name)
            if isinstance(n, N.For) and n.var == name:
                return n.var_span
            if isinstance(n, N.PBind) and n.name == name:
                return n.span
        return None

    def module_decl(self, module, name):
        """(decl, module) of a top-level `name` as seen from `module` (following imports)."""
        if module is None or module.program is None:
            return None, None
        for d in module.program.decls:
            if isinstance(d, (N.FnDecl, N.ConstDecl, N.TypeDecl, N.EnumDecl, N.AliasDecl, N.TraitDecl)) and \
                    d.name == name:
                return d, module
        dep = module.import_from.get(name)
        if dep is not None:
            return self.module_decl(dep[0], name)
        return None, None

    def type_decl(self, name):
        owner = self.loaded.universe.owner(name)
        if owner is None:
            return None, None
        return self.module_decl(self.modules.get(owner), name)

    def decl_span(self, d, module):
        if d is None:
            return None
        if isinstance(d, (N.FnDecl, N.ConstDecl, N.TraitDecl)):
            return d.name_span
        return find_word_span(self.lines_of(module.display), d.span, d.name) or d.span

    def target(self, node, top):
        """(kind, name, definition span or None, decl, module) of the symbol at the cursor."""
        if isinstance(node, tuple) and node[0] == "bound":
            d, m = self.type_decl(node[1])
            return "trait", node[1], self.decl_span(d, m), d, m
        if isinstance(node, N.Name):
            local = self.local_decl(top, node.name)
            if local is not None:
                return "local", node.name, local, None, self.main
            d, m = self.module_decl(self.main, node.name)
            if d is not None:
                return ("const" if isinstance(d, N.ConstDecl) else "fn"), node.name, self.decl_span(d, m), d, m
            return "builtin", node.name, None, None, None
        if isinstance(node, (N.Let, N.Param, N.For, N.PBind)):
            name = node.var if isinstance(node, N.For) else node.name
            return "local", name, self.name_span(node), None, self.main
        if isinstance(node, N.MethodCall):
            res = getattr(node, "resolved", None) or (None,)
            sig = getattr(node, "sig", None)
            if res[0] == "ufcs" and sig is not None and sig.decl is not None:
                m = self.modules.get(sig.module)
                return "method", node.method, sig.decl.name_span, sig.decl, m
            if res[0] == "trait":
                info = self.loaded.universe.traits.get(res[1])
                m = self.modules.get(info.module) if info else None
                for d in (m.program.decls if m and m.program else []):
                    if isinstance(d, N.TraitDecl) and d.name == res[1]:
                        for f in d.methods:
                            if f.method == node.method:
                                return "method", node.method, f.name_span, f, m
                    if isinstance(d, N.FnDecl) and d.owner_kind == "default" and d.trait == res[1] and \
                            d.method == node.method:
                        return "method", node.method, d.name_span, d, m
            if res[0] == "variant":
                d, m = self.type_decl(res[1])
                if d is not None:
                    for v in d.variants:
                        if v.name == node.method:
                            return "variant", node.method, find_word_span(self.lines_of(m.display), v.span, v.name), d, m
            if res[0] == "field_fn":
                return "field", node.method, None, None, None
            return "builtin_method", node.method, None, None, None
        if isinstance(node, N.FieldAccess):
            if isinstance(node.obj, N.Name) and node.obj.name in self.loaded.universe.enums:
                d, m = self.type_decl(node.obj.name)
                for v in d.variants if d is not None else []:
                    if v.name == node.name:
                        return "variant", node.name, find_word_span(self.lines_of(m.display), v.span, v.name), d, m
            t = prune(getattr(node.obj, "kt", None)) if getattr(node.obj, "kt", None) is not None else None
            h = head(t) if t is not None else None
            if h in self.loaded.universe.records:
                d, m = self.type_decl(h)
                for f in d.fields if d is not None and hasattr(d, "fields") else []:
                    if f.name == node.name:
                        return "field", node.name, find_word_span(self.lines_of(m.display), f.span, f.name), d, m
            return "field", node.name, None, None, None
        if isinstance(node, (N.TypeName, N.RecordLit, N.TypeDecl, N.EnumDecl, N.AliasDecl, N.TraitDecl)):
            name = node.type_name if isinstance(node, N.RecordLit) else node.name
            d, m = self.type_decl(name)
            return ("trait" if isinstance(d, N.TraitDecl) else "type"), name, self.decl_span(d, m), d, m
        if isinstance(node, N.PVariant):
            d, m = self.type_decl(node.enum)
            for v in d.variants if d is not None else []:
                if v.name == node.variant:
                    return "variant", node.variant, find_word_span(self.lines_of(m.display), v.span, v.name), d, m
        if isinstance(node, (N.FnDecl, N.ConstDecl)):
            name = node.method if getattr(node, "owner_kind", None) else node.name
            return ("const" if isinstance(node, N.ConstDecl) else "fn"), name, node.name_span, node, self.main
        return None, None, None, None, None


# ---- the server -----------------------------------------------------------------------------------------
class Server:
    def __init__(self, inp=None, out=None, log=None):
        self.inp = inp or sys.stdin.buffer
        self.out = out or sys.stdout.buffer
        self.log = log or sys.stderr
        self.docs = {}         # uri -> text
        self.analyses = {}     # uri -> Analysis (latest)
        self.good = {}         # uri -> latest Analysis whose file parsed (for completion while typing)
        self.running = True
        self.shutdown_requested = False

    # ---- transport ------------------------------------------------------------------------------------
    def read_message(self):
        headers = {}
        while True:
            line = self.inp.readline()
            if not line:
                return None
            line = line.decode("ascii", "replace").strip()
            if not line:
                break
            k, _, v = line.partition(":")
            headers[k.strip().lower()] = v.strip()
        n = int(headers.get("content-length", "0"))
        body = self.inp.read(n)
        return json.loads(body.decode("utf-8"))

    def send(self, msg):
        msg["jsonrpc"] = "2.0"
        data = json.dumps(msg, ensure_ascii=False).encode("utf-8")
        self.out.write(f"Content-Length: {len(data)}\r\n\r\n".encode("ascii") + data)
        self.out.flush()

    def notify(self, method, params):
        self.send({"method": method, "params": params})

    def serve(self):
        while self.running:
            msg = self.read_message()
            if msg is None:
                break
            self.handle(msg)
        return 0 if self.shutdown_requested else 1

    def handle(self, msg):
        method = msg.get("method")
        mid = msg.get("id")
        if getattr(self, "trace", False):
            print(f"<- {method or 'response'} {mid if mid is not None else ''}", file=self.log)
        params = msg.get("params") or {}
        if method == "exit":
            self.running = False
            return
        fn = getattr(self, "on_" + (method or "").replace("/", "_").replace("$", "S"), None)
        if fn is None:
            if mid is not None and method is not None:
                self.send({"id": mid, "error": {"code": -32601, "message": f"unsupported method {method}"}})
            return
        try:
            result = fn(params)
            if mid is not None:
                self.send({"id": mid, "result": result})
        except Exception as ex:  # a broken request must never take the server down
            traceback.print_exc(file=self.log)
            if mid is not None:
                self.send({"id": mid, "error": {"code": -32603, "message": f"{type(ex).__name__}: {ex}"}})

    # ---- lifecycle ------------------------------------------------------------------------------------
    def on_initialize(self, params):
        from .. import __version__
        return {"capabilities": {
            "textDocumentSync": {"openClose": True, "change": 1, "save": {"includeText": False}},
            "hoverProvider": True, "definitionProvider": True, "referencesProvider": True,
            "renameProvider": {"prepareProvider": True}, "documentSymbolProvider": True,
            "documentFormattingProvider": True,
            "completionProvider": {"triggerCharacters": ["."]},
            "signatureHelpProvider": {"triggerCharacters": ["(", ","]},
            "codeActionProvider": {"codeActionKinds": ["quickfix"]},
        }, "serverInfo": {"name": "klar", "version": __version__}}

    def on_initialized(self, params):
        return None

    def on_shutdown(self, params):
        self.shutdown_requested = True
        return None

    # ---- documents ------------------------------------------------------------------------------------
    def analyse(self, uri):
        text = self.docs.get(uri)
        if text is None:
            return None
        path = uri_to_path(uri)
        overlay = {uri_to_path(u): t for u, t in self.docs.items() if u != uri}
        a = Analysis(path, text, overlay)
        self.analyses[uri] = a
        if a.ok:
            self.good[uri] = a
        self.publish(uri, a)
        return a

    def reanalyse_all(self, first=None):
        if first is not None:
            self.analyse(first)
        for uri in list(self.docs):
            if uri != first:
                self.analyse(uri)

    def on_textDocument_didOpen(self, params):
        doc = params["textDocument"]
        self.docs[doc["uri"]] = doc["text"]
        self.reanalyse_all(doc["uri"])

    def on_textDocument_didChange(self, params):
        uri = params["textDocument"]["uri"]
        for ch in params["contentChanges"]:
            if "range" not in ch:
                self.docs[uri] = ch["text"]
            else:   # incremental change (we ask for full sync, but accept both)
                lines = self.docs.get(uri, "").split("\n")
                s, e = ch["range"]["start"], ch["range"]["end"]
                sl, sc = from_lsp_pos(lines, s)
                el, ec = from_lsp_pos(lines, e)
                text = self.docs.get(uri, "")
                a = offset(text, sl, sc)
                b = offset(text, el, ec)
                self.docs[uri] = text[:a] + ch["text"] + text[b:]
        self.reanalyse_all(uri)

    def on_textDocument_didSave(self, params):
        self.reanalyse_all(params["textDocument"]["uri"])

    def on_textDocument_didClose(self, params):
        uri = params["textDocument"]["uri"]
        self.docs.pop(uri, None)
        self.analyses.pop(uri, None)
        self.good.pop(uri, None)
        self.notify("textDocument/publishDiagnostics", {"uri": uri, "diagnostics": []})

    def publish(self, uri, a):
        out = []
        display = os.path.basename(a.path)
        for d in a.loaded.diags:
            if d.span.file != display:
                continue
            msg = d.message
            if d.hint:
                msg += f"\nhint: {d.hint}"
            for n in d.notes:
                msg += f"\nnote: {n}"
            diag = {"range": to_range(a.lines, d.span), "severity": SEV.get(d.severity, 3), "code": d.code,
                    "source": "klar", "message": msg}
            if d.fix:
                edits = []
                for e in fix_edits(d.fix):
                    sp = e["span"]
                    target = sp.file or d.span.file
                    edits.append({"uri": path_to_uri(a.path_of(target)),
                                  "range": to_range(a.lines_of(target), sp), "newText": e["text"]})
                title = d.hint or d.message
                if d.code == "E0606":
                    title = "make it public (`pub`)"
                diag["data"] = {"edits": edits, "title": title, "safe": d.fix.get("safe", True)}
            out.append(diag)
        self.notify("textDocument/publishDiagnostics", {"uri": uri, "diagnostics": out})

    def current(self, params):
        uri = params["textDocument"]["uri"]
        a = self.analyses.get(uri)
        if a is None and uri in self.docs:
            a = self.analyse(uri)
        return uri, a

    # ---- features -------------------------------------------------------------------------------------
    def on_textDocument_hover(self, params):
        uri, a = self.current(params)
        if a is None or not a.ok:
            return None
        line, col = from_lsp_pos(a.lines, params["position"])
        node, sp, top = a.node_at(line, col)
        if node is None:
            return None
        text = self.describe(a, node, top)
        if not text:
            return None
        return {"contents": {"kind": "markdown", "value": text}, "range": to_range(a.lines, sp)}

    def describe(self, a, node, top):
        kind, name, _, d, m = a.target(node, top)
        code = None
        doc = getattr(d, "doc", None) if d is not None else None
        if kind == "local":
            t = getattr(node, "kt", None)
            if t is None:
                for n in N.walk(top):
                    if isinstance(n, N.Name) and n.name == name and getattr(n, "kt", None) is not None:
                        t = n.kt
                        break
            code = f"{name}: {show(prune(t))}" if t is not None else name
        elif d is not None and m is not None:
            lines = a.lines_of(m.display)
            if isinstance(d, N.TraitDecl):
                ms = "\n".join("  " + sig_text(lines, f) for f in d.methods)
                code = f"trait {d.name} {{\n{ms}\n}}"
            else:
                code = sig_text(lines, d)
                if getattr(d, "public", False):
                    code = "pub " + code
            if kind == "variant":
                code = f"{d.name}.{name}  // variant of enum {d.name}"
            where = m.display if m is not a.main else None
            if getattr(d, "owner_kind", None) == "impl":
                where = f"impl {d.trait} for {d.owner}" + (f" — {m.display}" if m is not a.main else "")
            elif getattr(d, "owner_kind", None) == "default":
                where = f"default method of trait {d.trait}"
            elif getattr(d, "trait", None) and not getattr(d, "owner_kind", None):
                where = f"trait {d.trait}"
            if where:
                doc = (doc + "\n\n" if doc else "") + f"*{where}*"
        elif kind == "builtin" and name in GLOBALS:
            code = GLOBALS[name][0]
            doc = "built-in function"
        elif kind == "builtin_method":
            res = getattr(node, "resolved", None) or (None,)
            if res[0] == "builtin":
                code = METHODS[res[1]][res[2]][0]
                doc = f"built-in method of `{res[1]}`"
            elif res[0] == "to_str":
                code = "fn to_str(self) -> Str"
        elif kind == "field":
            t = getattr(node, "kt", None)
            code = f"{name}: {show(prune(t))}" if t is not None else name
        if code is None:
            t = getattr(node, "kt", None)
            if t is None:
                return None
            code = show(prune(t))
        out = f"```klar\n{code}\n```"
        if doc:
            out += "\n\n" + doc
        return out

    def on_textDocument_definition(self, params):
        uri, a = self.current(params)
        if a is None or not a.ok:
            return None
        line, col = from_lsp_pos(a.lines, params["position"])
        node, _, top = a.node_at(line, col)
        if node is None:
            return None
        kind, name, span, d, m = a.target(node, top)
        if span is None:
            return None
        if kind == "local":
            return {"uri": uri, "range": to_range(a.lines, span)}
        return a.location(span)

    def occurrences(self, a, node, top):
        """[(display file, Span)] of the symbol at the cursor (locals stay inside their declaration)."""
        kind, name, span, d, m = a.target(node, top)
        if kind is None or kind in ("builtin", "builtin_method"):
            return kind, name, []
        if kind == "local":
            display = a.main.display
            found = [(f, sp) for f, sp, _ in name_occurrences(a.loaded, name)
                     if f == display and top.span.line <= sp.line <= top.span.end_line]
            return kind, name, found
        return kind, name, [(f, sp) for f, sp, _ in name_occurrences(a.loaded, name)]

    def on_textDocument_references(self, params):
        uri, a = self.current(params)
        if a is None or not a.ok:
            return []
        line, col = from_lsp_pos(a.lines, params["position"])
        node, _, top = a.node_at(line, col)
        if node is None:
            return []
        _, _, occ = self.occurrences(a, node, top)
        return [loc for loc in (a.location(sp) for _, sp in occ) if loc is not None]

    def on_textDocument_prepareRename(self, params):
        uri, a = self.current(params)
        if a is None or not a.ok:
            return None
        line, col = from_lsp_pos(a.lines, params["position"])
        node, sp, top = a.node_at(line, col)
        if node is None:
            return None
        kind, name, _, _, _ = a.target(node, top)
        if kind in (None, "builtin", "builtin_method"):
            return None
        word = find_word_span(a.lines, sp, name) or sp
        return {"range": to_range(a.lines, word), "placeholder": name}

    def on_textDocument_rename(self, params):
        uri, a = self.current(params)
        if a is None or not a.ok:
            raise ValueError("fix the syntax errors first")
        new = params["newName"]
        line, col = from_lsp_pos(a.lines, params["position"])
        node, _, top = a.node_at(line, col)
        kind, old, occ = self.occurrences(a, node, top) if node is not None else (None, None, [])
        if not occ:
            raise ValueError("nothing to rename here")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", new):
            raise ValueError(f"`{new}` is not a valid name")
        if old[:1].isupper() != new[:1].isupper():
            raise ValueError("keep the case convention: types and variants PascalCase, values snake_case")
        if name_occurrences(a.loaded, new):
            raise ValueError(f"`{new}` is already used in the program (Klar forbids shadowing)")
        changes = {}
        for f, sp in occ:
            lines = a.lines_of(f)
            word = sp if sp.end_col - sp.col == len(old) and sp.line == sp.end_line else find_word_span(lines, sp, old)
            if word is None:
                continue
            u = path_to_uri(a.path_of(f))
            changes.setdefault(u, []).append({"range": to_range(lines, word), "newText": new})
        return {"changes": changes}

    def on_textDocument_documentSymbol(self, params):
        uri, a = self.current(params)
        if a is None or not a.ok:
            return []
        out = []
        decls = a.main.program.decls
        for i, d in enumerate(decls):
            kind = DECL_KINDS.get(type(d))
            if kind in (None, "use") or (kind == "test" and d.name.startswith("doc: ")):
                continue
            if kind == "fn" and (d.owner_kind or d.constructs):
                continue
            name = d.name if kind != "impl" else f"impl {d.trait} for {getattr(d.target, 'name', '?')}"
            sel = a.name_span(d) if not isinstance(d, (N.TestDecl, N.PropertyDecl, N.ImplDecl)) else None
            sym = {"name": name, "kind": SK.get(kind, 13), "range": to_range(a.lines, d.span),
                   "selectionRange": to_range(a.lines, sel or d.span)}
            if kind == "fn":
                sym["detail"] = sig_text(a.lines, d)
            children = []
            if kind == "impl":
                children = [f for f in decls[i + 1:i + 1 + len(d.methods)] if isinstance(f, N.FnDecl)]
            elif kind == "trait":
                children = list(d.methods) + [f for f in decls if isinstance(f, N.FnDecl)
                                              and f.owner_kind == "default" and f.trait == d.name]
            if children:
                sym["children"] = [{"name": f.method or f.name, "kind": SK["method"], "detail": sig_text(a.lines, f),
                                    "range": to_range(a.lines, f.span), "selectionRange": to_range(a.lines, f.name_span)}
                                   for f in children]
            out.append(sym)
        return out

    def on_textDocument_formatting(self, params):
        from .fmt import FormatError, format_checked
        uri = params["textDocument"]["uri"]
        text = self.docs.get(uri)
        if text is None:
            return None
        try:
            new = format_checked(text)
        except FormatError as ex:
            self.notify("window/showMessage", {"type": 2, "message": f"klar fmt: {ex}"})
            return None
        if new == text:
            return []
        lines = text.split("\n")
        end = {"line": len(lines), "character": 0}
        return [{"range": {"start": {"line": 0, "character": 0}, "end": end}, "newText": new}]

    def on_textDocument_codeAction(self, params):
        out = []
        for diag in params.get("context", {}).get("diagnostics", []):
            data = diag.get("data")
            if not data or not data.get("edits"):
                continue
            changes = {}
            for e in data["edits"]:
                changes.setdefault(e["uri"], []).append({"range": e["range"], "newText": e["newText"]})
            title = data.get("title") or "apply the fix"
            title = re.sub(r"^did you mean ", "replace with ", title)
            out.append({"title": f"Klar: {title}", "kind": "quickfix", "diagnostics": [diag],
                        "isPreferred": bool(data.get("safe", True)), "edit": {"changes": changes}})
        return out

    # ---- completion -------------------------------------------------------------------------------------
    def on_textDocument_completion(self, params):
        uri = params["textDocument"]["uri"]
        text = self.docs.get(uri, "")
        lines = text.split("\n")
        line, col = from_lsp_pos(lines, params["position"])
        prefix = lines[line - 1][:col - 1] if line - 1 < len(lines) else ""
        a = self.good.get(uri)
        m = re.search(r"([A-Za-z_][A-Za-z0-9_]*|\"|\]|\))\s*\.\s*([A-Za-z_][A-Za-z0-9_]*)?$", prefix)
        if m:
            return {"isIncomplete": False, "items": self.member_items(a, m.group(1), line)}
        return {"isIncomplete": False, "items": self.name_items(a, line)}

    def receiver_type(self, a, ident, line):
        if ident == '"':
            return TCon("Str")
        if ident in ("]",):
            return TCon("List", [TParam("T")])
        if a is None:
            return None
        for n in N.walk(a.main.program):
            if isinstance(n, N.Name) and n.name == ident and getattr(n, "kt", None) is not None:
                t = prune(n.kt)
                if head(t) is not None:
                    return t
        for n in N.walk(a.main.program):
            if isinstance(n, N.Let) and n.name == ident and getattr(n.value, "kt", None) is not None:
                return prune(n.value.kt)
        return None

    def member_items(self, a, ident, line):
        items = []
        if a is not None and ident in a.loaded.universe.enums:
            for v, fields in a.loaded.universe.enums[ident].variants.items():
                detail = f"{ident}.{v}" + (f"({', '.join(f for f, _ in fields)})" if fields else "")
                items.append({"label": v, "kind": CK["member"], "detail": detail})
            return items
        t = self.receiver_type(a, ident, line)
        h = head(t) if t is not None else None
        seen = set()

        def add(label, kind, detail, doc=None):
            if label in seen:
                return
            seen.add(label)
            item = {"label": label, "kind": CK[kind], "detail": detail}
            if doc:
                item["documentation"] = doc
            items.append(item)
        if h is None:
            return items
        if a is not None and h in a.loaded.universe.records:
            for f, ft in a.loaded.universe.records[h].fields.items():
                add(f, "field", f"{f}: {show(ft)}")
        for name, (sig, _) in sorted(METHODS.get(h, {}).items()):
            add(name, "method", sig)
        if a is not None:
            for name, (trait, sig) in sorted(a.loaded.universe.type_methods.get(h, {}).items()):
                add(name, "method", f"{trait}: {sig.name.split('.')[-1]}", None)
            for name, sig in sorted(a.main.checker.fns.items()):
                if sig is not None and sig.params and head(sig.params[0][1]) == h:
                    add(name, "function", f"fn {name}(...)")
        add("to_str", "method", "fn to_str(self) -> Str")
        return items

    def name_items(self, a, line):
        items = []
        seen = set()

        def add(label, kind, detail=None, insert=None):
            if label in seen:
                return
            seen.add(label)
            item = {"label": label, "kind": CK[kind]}
            if detail:
                item["detail"] = detail
            if insert:
                item["insertText"] = insert
                item["insertTextFormat"] = 2
            items.append(item)
        if a is not None:
            for d in a.main.program.decls:
                if d.span.line <= line <= d.span.end_line:
                    for n in N.walk(d):
                        if isinstance(n, (N.Let, N.Param, N.PBind)) and n.name != "self" or isinstance(n, N.For):
                            name = n.var if isinstance(n, N.For) else n.name
                            t = getattr(n, "kt", None) or getattr(getattr(n, "value", None), "kt", None)
                            add(name, "variable", show(prune(t)) if t is not None else None)
            chk = a.main.checker
            for name, sig in sorted(chk.fns.items()):
                if sig is not None:
                    ps = ", ".join(f"{p}: {show(t)}" for p, t in sig.params)
                    add(name, "function", f"fn {name}({ps}) -> {show(sig.ret)}")
            for name, t in sorted(chk.consts.items()):
                add(name, "constant", show(t) if t is not None else None)
            for name in sorted(chk.visible):
                u = a.loaded.universe
                kind = "interface" if name in u.traits else "enum" if name in u.enums else "struct"
                add(name, kind)
        for name, (sig, _) in sorted(GLOBALS.items()):
            add(name, "function", sig)
        for t in ("Int", "Float", "Bool", "Str", "Unit", "List", "Map", "Option", "Result"):
            add(t, "class")
        for kw in KEYWORDS:
            add(kw, "keyword")
        for name, body in SNIPPETS.items():
            items.append({"label": name, "kind": CK["snippet"], "insertText": body, "insertTextFormat": 2,
                          "detail": "snippet"})
        return items

    # ---- signature help ---------------------------------------------------------------------------------
    def on_textDocument_signatureHelp(self, params):
        uri = params["textDocument"]["uri"]
        text = self.docs.get(uri, "")
        lines = text.split("\n")
        line, col = from_lsp_pos(lines, params["position"])
        upto = text[:offset(text, line, col)]
        stack = []                 # [open bracket, its offset, commas seen inside it]
        in_str = False
        k = 0
        while k < len(upto):
            c = upto[k]
            if in_str:
                if c == "\\":
                    k += 1
                elif c == '"':
                    in_str = False
            elif c == '"':
                in_str = True
            elif c == "/" and upto[k + 1:k + 2] == "/":
                nl = upto.find("\n", k)
                k = len(upto) if nl < 0 else nl
                continue
            elif c in "([{":
                stack.append([c, k, 0])
            elif c in ")]}":
                if stack:
                    stack.pop()
            elif c == "," and stack:
                stack[-1][2] += 1
            k += 1
        calls = [s for s in stack if s[0] == "("]
        if not calls:
            return None
        _, i, commas = calls[-1]
        m = re.search(r"(\.)?\s*([A-Za-z_][A-Za-z0-9_]*)\s*$", upto[:i])
        if not m:
            return None
        name, is_method = m.group(2), bool(m.group(1))
        a = self.good.get(uri)
        sigs = self.signatures(a, name, is_method)
        if not sigs:
            return None
        return {"signatures": sigs, "activeSignature": 0, "activeParameter": commas}

    def signatures(self, a, name, is_method):
        out = []

        def from_text(sig, skip_self):
            m = re.match(r"fn\s+[A-Za-z_][\w.]*(\[[^\]]*\])?\((.*)\)(.*)$", sig)
            if not m:
                return None
            params = split_params(m.group(2))
            if skip_self and params and (params[0].startswith("self:") or params[0] == "self"):
                params = params[1:]
            label = f"{name}({', '.join(params)}){m.group(3)}"
            return {"label": label, "parameters": [{"label": p} for p in params]}
        if a is not None:
            sig = a.main.checker.fns.get(name)
            if sig is not None and sig.decl is not None:
                m = a.modules.get(sig.module)
                text = sig_text(a.lines_of(m.display) if m else a.lines, sig.decl)
                s = from_text(text, is_method)
                if s:
                    if sig.decl.doc:
                        s["documentation"] = sig.decl.doc
                    out.append(s)
            if is_method:
                for methods in a.loaded.universe.type_methods.values():
                    if name in methods:
                        msig = methods[name][1]
                        mm = a.modules.get(msig.module)
                        if msig.decl is not None and mm is not None:
                            s = from_text(sig_text(a.lines_of(mm.display), msig.decl), True)
                            if s and s["label"] not in [o["label"] for o in out]:
                                out.append(s)
        if is_method:
            for owner, ms in METHODS.items():
                if name in ms:
                    s = from_text(ms[name][0], True)
                    if s and s["label"] not in [o["label"] for o in out]:
                        s["label"] = f"{owner}." + s["label"]
                        out.append(s)
        elif name in GLOBALS:
            s = from_text(GLOBALS[name][0], False)
            if s:
                out.append(s)
        return out[:6]


def split_params(text):
    out, depth, cur = [], 0, ""
    for c in text:
        if c in "([":
            depth += 1
        elif c in ")]":
            depth -= 1
        if c == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += c
    if cur.strip():
        out.append(cur.strip())
    return out


def offset(text, line, col):
    """Character offset of a 1-based (line, col)."""
    pos = 0
    for _ in range(line - 1):
        nl = text.find("\n", pos)
        if nl < 0:
            return len(text)
        pos = nl + 1
    return min(pos + col - 1, len(text))


def main():
    """Run the server; set KLAR_LSP_LOG=/path/to/file to log every message and error (debugging editors)."""
    log_path = os.environ.get("KLAR_LSP_LOG")
    log = open(log_path, "a", encoding="utf-8", buffering=1) if log_path else sys.stderr
    server = Server(log=log)
    server.trace = bool(log_path)
    try:
        return server.serve()
    except Exception:
        traceback.print_exc(file=log)
        raise


def cmd_lsp(args):
    return main()


def register(sub):
    p = sub.add_parser("lsp", help="run the language server (LSP over stdin/stdout) for editors")
    # flags that LSP clients add on their own (vscode-languageclient passes --stdio)
    p.add_argument("--stdio", action="store_true", help="communicate over stdin/stdout (the default and only mode)")
    p.add_argument("--clientProcessId", help=argparse.SUPPRESS)
    p.set_defaults(fn=cmd_lsp)
