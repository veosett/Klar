"""Recursive-descent parser for Klar.

Precedence (low -> high):
  or < and < not < comparison (non-chaining) < + - < * / % < unary - < postfix (call . ? with)
"""
from typing import List

from . import nodes as N
from .diagnostics import Diagnostic, KlarSyntaxError, Span
from .lexer import Token, tokenize

CMP_OPS = {"==", "!=", "<", ">", "<=", ">="}


class Parser:
    def __init__(self, tokens: List[Token], file: str):
        self.t = tokens
        self.p = 0
        self.file = file
        self.no_struct = False  # disables `Name { ... }` literals in conditions

    # ---- token helpers ----------------------------------------------------
    @property
    def cur(self) -> Token:
        return self.t[self.p]

    def peek(self, k=1) -> Token:
        return self.t[min(self.p + k, len(self.t) - 1)]

    def prev(self) -> Token:
        return self.t[self.p - 1]

    def advance(self) -> Token:
        tok = self.t[self.p]
        if tok.kind != "EOF":
            self.p += 1
        return tok

    def at(self, kind, value=None) -> bool:
        tok = self.cur
        return tok.kind == kind and (value is None or tok.value == value)

    def at_op(self, v):
        return self.at("OP", v)

    def at_kw(self, v):
        return self.at("KW", v)

    def accept_op(self, v) -> bool:
        if self.at_op(v):
            self.advance()
            return True
        return False

    def accept_kw(self, v) -> bool:
        if self.at_kw(v):
            self.advance()
            return True
        return False

    def fail(self, msg, tok=None, hint=None, code="E0003", fix=None):
        tok = tok or self.cur
        raise KlarSyntaxError(Diagnostic(code, "error", msg, tok.span, hint, fix))

    def expect_op(self, v, ctx="", hint=None) -> Token:
        if self.at_op(v):
            return self.advance()
        self.fail(f"expected `{v}`{ctx}, found {self.cur.describe()}", hint=hint)

    def expect_ident(self, what) -> Token:
        if self.at("IDENT"):
            return self.advance()
        hint = None
        if self.cur.kind == "KW":
            hint = f"`{self.cur.value}` is a reserved keyword and cannot be used as a name"
        self.fail(f"expected {what}, found {self.cur.describe()}", hint=hint)

    def skip_nl(self):
        while self.cur.kind in ("NEWLINE", "DOC"):
            self.advance()

    def span_from(self, start: Span) -> Span:
        return start.merge(self.prev().span)

    def end_of_statement(self):
        if self.at("NEWLINE"):
            self.skip_nl()
        elif not (self.at_op("}") or self.at("EOF")):
            self.fail(f"expected end of line after statement, found {self.cur.describe()}",
                      hint="put each statement on its own line")

    # ---- program ----------------------------------------------------------
    def parse_program(self) -> N.Program:
        start = self.cur.span
        module = None
        while self.at("NEWLINE"):
            self.advance()
        if self.accept_kw("module"):
            parts = [self.expect_ident("module name").value]
            while self.accept_op("."):
                parts.append(self.expect_ident("module name").value)
            module = ".".join(parts)
            if not self.at("NEWLINE"):
                self.fail(f"expected end of line after module name, found {self.cur.describe()}")
        decls = []
        seen_other = False
        while True:
            docs = []
            while self.cur.kind in ("NEWLINE", "DOC"):
                tok = self.advance()
                if tok.kind == "DOC":
                    docs.append(tok)
            if self.at("EOF"):
                break
            doc = "\n".join(t.value.strip() for t in docs if not t.value.strip().startswith(">>>")) or None
            if self.at_kw("use"):
                if seen_other:
                    self.fail("`use` must come before all other declarations",
                              hint="move the `use` lines to the top of the file")
                decls.append(self.parse_use())
            else:
                seen_other = True
                pub_tok = self.cur if self.accept_kw("pub") else None
                if pub_tok is not None and not any(self.at_kw(k) for k in ("fn", "type", "enum", "const", "trait")):
                    self.fail(f"`pub` goes before `fn`, `type`, `enum`, `const` or `trait`, found {self.cur.describe()}",
                              hint="impls, tests and `use` have no visibility: an impl is visible wherever its "
                                   "trait is" if self.at_kw("impl") else None)
                if self.at_kw("fn"):
                    d = self.parse_fn(doc)
                elif self.at_kw("type"):
                    d = self.parse_type_decl(doc)
                elif self.at_kw("enum"):
                    d = self.parse_enum_decl(doc)
                elif self.at_kw("const"):
                    d = self.parse_const(doc)
                elif self.at_kw("test"):
                    d = self.parse_test()
                elif self.at_kw("property"):
                    d = self.parse_property()
                elif self.at_kw("trait") or self.at_kw("impl"):
                    group = self.parse_trait(doc) if self.at_kw("trait") else self.parse_impl()
                    group[0].public = pub_tok is not None
                    decls.extend(group)
                    doctest = self.doctest(docs, group[0])
                    if doctest is not None:
                        decls.append(doctest)
                    if not (self.at("NEWLINE") or self.at("EOF")):
                        self.fail(f"expected end of line after declaration, found {self.cur.describe()}")
                    continue
                elif self.at_kw("let") or self.at_kw("var"):
                    self.fail("top-level variables are not allowed",
                              hint="declare a constant: `const MAX_USERS: Int = 100`")
                else:
                    self.fail("expected a declaration (`fn`, `type`, `enum`, `trait`, `impl`, `const`, `test`, "
                              "`property`, `use`), "
                              f"found {self.cur.describe()}")
                if pub_tok is not None:
                    d.public = True
                decls.append(d)
                doctest = self.doctest(docs, d)
                if doctest is not None:
                    decls.append(doctest)
            if not (self.at("NEWLINE") or self.at("EOF")):
                self.fail(f"expected end of line after declaration, found {self.cur.describe()}")
        return N.Program(span=start.merge(self.cur.span), module=module, decls=decls, file=self.file)

    def doctest(self, docs, decl):
        """Lines `/// >>> stmt` in a doc comment become a test named `doc: <decl>`."""
        stmts = []
        for tok in docs:
            raw = tok.value
            rest = raw.lstrip()
            if not rest.startswith(">>>"):
                continue
            code = rest[3:]
            col = tok.span.col + 3 + (len(raw) - len(rest)) + 3 + (len(code) - len(code.lstrip()))
            code = code.strip()
            if not code:
                continue
            sub = Parser(tokenize(code, self.file, tok.span.line, col), self.file)
            stmt = sub.parse_stmt()
            sub.skip_nl()
            if not sub.at("EOF"):
                sub.fail(f"unexpected {sub.cur.describe()} in doc-test line")
            stmts.append(stmt)
        if not stmts:
            return None
        name = getattr(decl, "name", "?")
        span = docs[0].span.merge(docs[-1].span)
        return N.TestDecl(span=span, name=f"doc: {name}", body=N.Block(span=span, stmts=stmts))

    def parse_type_params(self, allow_bounds=False):
        tparams = []
        self.last_bounds = {}
        if self.accept_op("["):
            while not self.at_op("]"):
                tp = self.expect_ident("type parameter")
                tparams.append(tp.value)
                if self.accept_op(":"):
                    if not allow_bounds:
                        self.fail("trait bounds are only allowed on functions", tok=self.prev(),
                                  hint="write the bound where the type is used: `fn f[T: Shape](x: T)`")
                    bounds = []
                    while True:
                        tr = self.expect_ident("trait name")
                        bounds.append((tr.value, tr.span))
                        if not self.accept_op("+"):
                            break
                    self.last_bounds[tp.value] = bounds
                if not self.accept_op(","):
                    break
            self.expect_op("]")
        elif self.at_op("<"):
            self.fail("type parameters use square brackets", hint="write `[T]`, e.g. `fn first[T](xs: List[T])`")
        return tparams

    def parse_use(self) -> N.UseDecl:
        start = self.advance().span
        path = [self.expect_ident("module name").value]
        items, spans = [], []
        while True:
            if not self.accept_op("."):
                self.fail("expected `.{ ... }` with the imported names",
                          hint=f"write `use {'.'.join(path)}.{{name1, name2}}` (explicit imports only)")
            if self.at_op("{"):
                self.advance()
                while not self.at_op("}"):
                    tok = self.expect_ident("imported name")
                    items.append(tok.value)
                    spans.append(tok.span)
                    if not self.accept_op(","):
                        break
                self.expect_op("}")
                break
            if self.at_op("*"):
                self.fail("wildcard imports are not allowed", hint="list the names: `use mod.{a, b}`")
            path.append(self.expect_ident("module name").value)
        if not items:
            self.fail("`use` must import at least one name", tok=self.prev())
        return N.UseDecl(span=self.span_from(start), path=path, items=items, item_spans=spans)

    def parse_const(self, doc) -> N.ConstDecl:
        start = self.advance().span
        name = self.expect_ident("constant name")
        if not self.accept_op(":"):
            self.fail(f"constant `{name.value}` needs a type", hint=f"write `const {name.value}: Int = ...`")
        ctype = self.parse_type()
        self.expect_op("=", f" after the type of `{name.value}`")
        value = self.parse_expr()
        return N.ConstDecl(span=self.span_from(start), name=name.value, name_span=name.span, type=ctype,
                           value=value, doc=doc)

    def parse_property(self) -> N.PropertyDecl:
        start = self.advance().span
        if not self.at("STR"):
            self.fail("expected a property name string", hint='write `property "reverse twice" (xs: List[Int]) { ... }`')
        name = self.advance().value
        self.expect_op("(", " with the generated inputs", hint='write `property "name" (x: Int, xs: List[Int]) { ... }`')
        params = self.parse_params(require_types=True)
        self.expect_op(")")
        self.skip_nl()
        body = self.parse_block()
        return N.PropertyDecl(span=self.span_from(start), name=name, params=params, body=body)

    # ---- declarations -------------------------------------------------------
    def parse_fn(self, doc=None, with_body=True, method_of=None) -> N.FnDecl:
        start = self.advance().span  # fn
        if self.at_op("("):
            self.fail("top-level functions need a name: `fn name(...)`")
        name_tok = self.expect_ident("function name")
        tparams = self.parse_type_params(allow_bounds=True)
        bounds = self.last_bounds
        self.expect_op("(", " after function name")
        params = self.parse_params(require_types=True, method_of=method_of)
        self.expect_op(")", " to close the parameter list")
        ret = None
        if self.accept_op("->"):
            ret = self.parse_type()
        elif self.at_op(":"):
            self.fail("return types are written with `->`", hint="write `fn f(x: Int) -> Int`")
        effects = []
        eff_span = None
        sig_end = self.prev().span
        if self.at_kw("uses"):
            eff_start = self.advance().span
            while True:
                effects.append(self.expect_ident("effect name (io, time, rand, fs, net, proc)").value)
                if not self.accept_op(","):
                    break
            eff_span = self.span_from(eff_start)
            sig_end = self.prev().span
        requires, ensures = [], []
        while True:
            save = self.p
            self.skip_nl()
            if self.accept_kw("requires"):
                requires.append(self.parse_expr_ns())
            elif self.accept_kw("ensures"):
                ensures.append(self.parse_expr_ns())
            else:
                self.p = save
                break
        body = None
        if with_body:
            self.skip_nl()
            if not self.at_op("{"):
                hint = None
                if self.at_op("=") or self.at_op("=>"):
                    hint = "function bodies are blocks: `fn f(x: Int) -> Int { return x * 2 }`"
                self.fail(f"expected `{{` to start the body of `{name_tok.value}`, found {self.cur.describe()}", hint=hint)
            body = self.parse_block()
        return N.FnDecl(span=self.span_from(start), name=name_tok.value, name_span=name_tok.span,
                        type_params=tparams, params=params, ret=ret, effects=effects,
                        effects_span=eff_span, sig_end=sig_end, requires=requires,
                        ensures=ensures, body=body, doc=doc, bounds=bounds)

    def parse_params(self, require_types: bool, method_of=None) -> List[N.Param]:
        params = []
        while not self.at_op(")"):
            tok = self.expect_ident("parameter name")
            ptype = None
            if tok.value == "self" and method_of is not None and not params:
                if self.at_op(":"):
                    self.fail("`self` has no type annotation: its type is the implementing type", tok=self.cur,
                              hint="write just `self`")
                params.append(N.Param(span=tok.span, name="self", type=N.TypeName(span=tok.span, name="Self", args=[])))
                if not self.accept_op(","):
                    break
                continue
            if tok.value == "self" and not self.at_op(":"):
                self.fail("an untyped `self` is only allowed as the first parameter of a `trait` or `impl` method",
                          tok=tok, hint="give the parameter a type, or move the function into an `impl` block")
            if self.accept_op(":"):
                ptype = self.parse_type()
            elif require_types:
                self.fail(f"parameter `{tok.value}` needs a type", tok=tok,
                          hint=f"write `{tok.value}: Int` (or the right type)")
            params.append(N.Param(span=self.span_from(tok.span), name=tok.value, type=ptype))
            if not self.accept_op(","):
                break
        return params

    def parse_type(self):
        start = self.cur.span
        if self.accept_kw("fn"):
            self.expect_op("(", " in function type")
            ps = []
            while not self.at_op(")"):
                ps.append(self.parse_type())
                if not self.accept_op(","):
                    break
            self.expect_op(")")
            self.expect_op("->", " in function type", hint="function types look like `fn(Int, Str) -> Bool`")
            ret = self.parse_type()
            return N.FnTypeExpr(span=self.span_from(start), params=ps, ret=ret)
        if self.at_op("("):
            self.fail("tuples are not supported in Klar 0.1", hint="define a record: `type Pair { a: Int, b: Int }`; for no value use `Unit`")
        tok = self.expect_ident("a type")
        args = []
        if self.accept_op("["):
            while not self.at_op("]"):
                args.append(self.parse_type())
                if not self.accept_op(","):
                    break
            self.expect_op("]")
        elif self.at_op("<"):
            self.fail("type arguments use square brackets", hint=f"write `{tok.value}[...]`, e.g. `List[Int]`")
        return N.TypeName(span=self.span_from(start), name=tok.value, args=args)

    def parse_field_decls(self, closer: str) -> List[N.FieldDecl]:
        fields = []
        self.skip_nl()
        while not self.at_op(closer):
            tok = self.expect_ident("field name")
            self.expect_op(":", f" after field `{tok.value}`", hint=f"fields are written `{tok.value}: Type`")
            ftype = self.parse_type()
            fields.append(N.FieldDecl(span=self.span_from(tok.span), name=tok.value, type=ftype))
            self.accept_op(",")
            self.skip_nl()
        return fields

    def method_block(self, what, method_of):
        """`{ [doc] fn ... }` of a trait or impl: returns [(FnDecl, doc tokens)]."""
        self.expect_op("{", f" to start the body of the {what}")
        out = []
        while True:
            docs = []
            while self.cur.kind in ("NEWLINE", "DOC"):
                tok = self.advance()
                if tok.kind == "DOC":
                    docs.append(tok)
            if self.at_op("}"):
                self.advance()
                return out
            if not self.at_kw("fn"):
                self.fail(f"a {what} contains only methods (`fn name(self, ...)`), found {self.cur.describe()}")
            doc = "\n".join(t.value.strip() for t in docs if not t.value.strip().startswith(">>>")) or None
            f = self.parse_fn(doc, with_body=False, method_of=method_of)
            save = self.p
            self.skip_nl()
            if not self.at_op("{"):
                self.p = save
            if self.at_op("{"):
                f.body = self.parse_block()
                f.span = f.span.merge(self.prev().span)
            elif what == "impl":
                self.fail(f"method `{f.name}` in an impl needs a body", hint="write `fn name(self) -> T { ... }`")
            if not f.params or f.params[0].name != "self":
                self.fail(f"method `{f.name}` must take `self` as its first parameter", tok=self.prev(),
                          hint=f"write `fn {f.name}(self, ...)`; functions without `self` belong outside the {what}")
            out.append((f, docs))
            if not (self.at("NEWLINE") or self.at_op("}")):
                self.fail(f"expected end of line after method `{f.name}`, found {self.cur.describe()}")

    def parse_trait(self, doc) -> list:
        start = self.advance().span
        name = self.expect_ident("trait name")
        if self.at_op("["):
            self.fail("generic traits are not supported yet", hint="declare the trait without type parameters")
        out_methods, defaults, extra = [], [], []
        for f, docs in self.method_block("trait", name.value):
            f.trait = name.value
            f.method = f.name
            if f.body is None:
                out_methods.append(f)
            else:
                defaults.append(f.name)
                f.owner_kind, f.owner = "default", name.value
                f.name = f"{name.value}.{f.method}"
                if f.type_params:
                    self.fail(f"trait method `{f.method}` cannot have its own type parameters (not supported yet)")
                f.type_params = ["Self"]
                f.bounds = {"Self": [(name.value, name.span)]}
                extra.append(f)
                t = self.doctest(docs, f)
                if t is not None:
                    extra.append(t)
        decl = N.TraitDecl(span=self.span_from(start), name=name.value, name_span=name.span, methods=out_methods,
                           defaults=defaults, doc=doc)
        return [decl] + extra

    def parse_impl(self) -> list:
        start = self.advance().span
        if self.at_op("["):
            self.fail("generic impls are not supported yet", hint="write `impl Trait for Type` for a concrete type")
        trait = self.expect_ident("trait name")
        if not self.accept_kw("for"):
            self.fail("expected `for` after the trait name", hint=f"write `impl {trait.value} for TypeName {{ ... }}`")
        target = self.parse_type()
        tname = getattr(target, "name", "?")
        methods, extra = [], []
        for f, docs in self.method_block("impl", tname):
            f.owner_kind, f.owner, f.trait, f.method = "impl", tname, trait.value, f.name
            f.name = f"{tname}.{f.method}"
            if f.type_params:
                self.fail(f"method `{f.method}` cannot have its own type parameters (not supported yet)")
            methods.append(f)
            t = self.doctest(docs, f)
            if t is not None:
                extra.append(t)
        decl = N.ImplDecl(span=self.span_from(start), trait=trait.value, trait_span=trait.span, target=target,
                          methods=[f.method for f in methods], method_spans=[f.name_span for f in methods])
        return [decl] + methods + extra

    def parse_type_decl(self, doc) -> N.TypeDecl:
        start = self.advance().span
        name = self.expect_ident("type name")
        tparams = self.parse_type_params()
        if self.accept_op("="):
            if self.at_op("{"):
                self.fail("record types are declared without `=`", hint=f"write `type {name.value} {{ field: Int }}`")
            target = self.parse_type()
            return N.AliasDecl(span=self.span_from(start), name=name.value, type_params=tparams, target=target, doc=doc)
        self.expect_op("{", f" after `type {name.value}`",
                       hint=f"records: `type {name.value} {{ x: Int }}`; aliases: `type {name.value} = Int`")
        fields = self.parse_field_decls("}")
        self.expect_op("}")
        return N.TypeDecl(span=self.span_from(start), name=name.value, type_params=tparams, fields=fields, doc=doc)

    def parse_enum_decl(self, doc) -> N.EnumDecl:
        start = self.advance().span
        name = self.expect_ident("enum name")
        tparams = self.parse_type_params()
        self.expect_op("{", f" after `enum {name.value}`")
        variants = []
        self.skip_nl()
        while not self.at_op("}"):
            vt = self.expect_ident("variant name")
            vfields = []
            if self.accept_op("("):
                if self.at("IDENT") and not (self.peek().kind == "OP" and self.peek().value == ":"):
                    self.fail("variant fields need names", hint=f"write `{vt.value}(value: {self.cur.value})`")
                vfields = self.parse_field_decls(")")
                self.expect_op(")")
            variants.append(N.VariantDecl(span=self.span_from(vt.span), name=vt.value, fields=vfields))
            self.accept_op(",")
            self.skip_nl()
        self.expect_op("}")
        return N.EnumDecl(span=self.span_from(start), name=name.value, type_params=tparams, variants=variants, doc=doc)

    def parse_test(self) -> N.TestDecl:
        start = self.advance().span
        if not self.at("STR"):
            self.fail("expected a test name string", hint='write `test "adds numbers" { ... }`')
        name = self.advance().value
        self.skip_nl()
        body = self.parse_block()
        return N.TestDecl(span=self.span_from(start), name=name, body=body)

    # ---- statements ---------------------------------------------------------
    def parse_block(self) -> N.Block:
        start = self.expect_op("{").span
        old = self.no_struct
        self.no_struct = False
        stmts = []
        self.skip_nl()
        while not self.at_op("}"):
            if self.at("EOF"):
                self.fail("unclosed `{`: reached end of file", hint="add the missing `}`")
            stmts.append(self.parse_stmt())
            self.end_of_statement()
        self.expect_op("}")
        self.no_struct = old
        return N.Block(span=self.span_from(start), stmts=stmts)

    def parse_stmt(self):
        tok = self.cur
        start = tok.span
        if tok.kind == "KW":
            kw = tok.value
            if kw in ("let", "var"):
                self.advance()
                name = self.expect_ident("variable name")
                vtype = None
                if self.accept_op(":"):
                    vtype = self.parse_type()
                if not self.at_op("="):
                    self.fail(f"`{kw} {name.value}` needs an initial value",
                              hint=f"write `{kw} {name.value} = ...`; Klar has no uninitialized variables")
                self.advance()
                value = self.parse_expr()
                return N.Let(span=self.span_from(start), name=name.value, name_span=name.span,
                             kw_span=tok.span, type=vtype, value=value, mutable=(kw == "var"))
            if kw == "return":
                self.advance()
                value = None
                if not (self.at("NEWLINE") or self.at_op("}")):
                    value = self.parse_expr()
                return N.Return(span=self.span_from(start), value=value)
            if kw == "if":
                return self.parse_if()
            if kw == "while":
                self.advance()
                cond = self.parse_expr_ns()
                body = self.parse_block()
                return N.While(span=self.span_from(start), cond=cond, body=body)
            if kw == "for":
                self.advance()
                var = self.expect_ident("loop variable")
                if not self.accept_kw("in"):
                    self.fail("expected `in` in for loop", hint="write `for item in items { ... }` or `for i in range(0, 10) { ... }`")
                it = self.parse_expr_ns()
                body = self.parse_block()
                return N.For(span=self.span_from(start), var=var.value, var_span=var.span, iter=it, body=body)
            if kw == "break":
                self.advance()
                return N.Break(span=start)
            if kw == "continue":
                self.advance()
                return N.Continue(span=start)
            if kw == "assert":
                self.advance()
                cond = self.parse_expr()
                msg = None
                if self.accept_op(","):
                    msg = self.parse_expr()
                return N.Assert(span=self.span_from(start), cond=cond, message=msg)
        expr = self.parse_expr()
        if self.at_op("="):
            if isinstance(expr, N.Name):
                self.advance()
                value = self.parse_expr()
                return N.Assign(span=self.span_from(start), name=expr.name, value=value)
            if isinstance(expr, N.FieldAccess):
                self.fail("record fields cannot be assigned (values are immutable)", tok=self.cur,
                          hint="create an updated copy: `rec = rec with { field: new_value }` (requires `var rec`)",
                          code="E0207")
            self.fail("invalid assignment target", hint="only variables declared with `var` can be assigned")
        return N.ExprStmt(span=self.span_from(start), expr=expr)

    def parse_if(self) -> N.If:
        start = self.advance().span
        cond = self.parse_expr_ns()
        if not self.at_op("{"):
            self.fail(f"expected `{{` after if condition, found {self.cur.describe()}",
                      hint="write `if cond { ... }` (no `then`, no parentheses needed)")
        then = self.parse_block()
        else_ = None
        save = self.p
        self.skip_nl()
        if self.accept_kw("else"):
            if self.at_kw("if"):
                else_ = self.parse_if()
            else:
                if not self.at_op("{"):
                    self.fail("expected `{` or `if` after `else`")
                else_ = self.parse_block()
        else:
            self.p = save
        return N.If(span=self.span_from(start), cond=cond, then=then, else_=else_)

    # ---- expressions --------------------------------------------------------
    def parse_expr_ns(self):
        old = self.no_struct
        self.no_struct = True
        try:
            return self.parse_expr()
        finally:
            self.no_struct = old

    def parse_expr(self):
        return self.parse_or()

    def parse_or(self):
        left = self.parse_and()
        while self.at_kw("or"):
            self.advance()
            self.skip_nl()
            right = self.parse_and()
            left = N.Binary(span=left.span.merge(right.span), op="or", left=left, right=right)
        return left

    def parse_and(self):
        left = self.parse_not()
        while self.at_kw("and"):
            self.advance()
            self.skip_nl()
            right = self.parse_not()
            left = N.Binary(span=left.span.merge(right.span), op="and", left=left, right=right)
        return left

    def parse_not(self):
        if self.at_kw("not"):
            start = self.advance().span
            operand = self.parse_not()
            return N.Unary(span=start.merge(operand.span), op="not", operand=operand)
        return self.parse_cmp()

    def parse_cmp(self):
        left = self.parse_add()
        if self.cur.kind == "OP" and self.cur.value in CMP_OPS:
            op = self.advance().value
            self.skip_nl()
            right = self.parse_add()
            left = N.Binary(span=left.span.merge(right.span), op=op, left=left, right=right)
            if self.cur.kind == "OP" and self.cur.value in CMP_OPS:
                self.fail("comparisons cannot be chained", hint="write `a < b and b < c`")
        return left

    def parse_add(self):
        left = self.parse_mul()
        while self.cur.kind == "OP" and self.cur.value in ("+", "-"):
            op = self.advance().value
            self.skip_nl()
            right = self.parse_mul()
            left = N.Binary(span=left.span.merge(right.span), op=op, left=left, right=right)
        return left

    def parse_mul(self):
        left = self.parse_unary()
        while self.cur.kind == "OP" and self.cur.value in ("*", "/", "%"):
            op = self.advance().value
            self.skip_nl()
            right = self.parse_unary()
            left = N.Binary(span=left.span.merge(right.span), op=op, left=left, right=right)
        return left

    def parse_unary(self):
        if self.at_op("-"):
            if self.peek(1).kind in ("INT", "FLOAT") and self.peek(2).kind == "OP" and self.peek(2).value in (".", "?"):
                lit = self.peek(1).value
                sp = self.cur.span.merge(self.peek(1).span)
                self.fail(f"`-{lit}.method()` is ambiguous: the method runs before the minus",
                          hint=f"write `(-{lit}).method()` for the negative number, or `-({lit}.method())`",
                          fix={"span": sp, "text": f"(-{lit})"})
            start = self.advance().span
            operand = self.parse_unary()
            if isinstance(operand, N.IntLit):
                return N.IntLit(span=start.merge(operand.span), value=-operand.value)
            if isinstance(operand, N.FloatLit):
                return N.FloatLit(span=start.merge(operand.span), value=-operand.value)
            return N.Unary(span=start.merge(operand.span), op="-", operand=operand)
        return self.parse_postfix(self.parse_primary())

    def parse_args(self) -> List[N.Arg]:
        self.expect_op("(")
        old = self.no_struct
        self.no_struct = False
        args = []
        while not self.at_op(")"):
            start = self.cur.span
            name = None
            if self.at("IDENT") and self.peek().kind == "OP" and self.peek().value == ":":
                name = self.advance().value
                self.advance()
            elif self.at("IDENT") and self.peek().kind == "OP" and self.peek().value == "=":
                self.fail("named arguments use `:`", hint=f"write `{self.cur.value}: value`")
            value = self.parse_expr()
            args.append(N.Arg(span=self.span_from(start), name=name, value=value))
            if not self.accept_op(","):
                break
        self.expect_op(")", " to close the argument list")
        self.no_struct = old
        return args

    def parse_postfix(self, expr):
        while True:
            if self.at_op("("):
                args = self.parse_args()
                expr = N.Call(span=self.span_from(expr.span), callee=expr, args=args)
            elif self.at_op("."):
                self.advance()
                if self.at("INT"):
                    self.fail("tuple indexing is not supported", hint="use a record with named fields")
                name = self.expect_ident("field or method name after `.`")
                if self.at_op("("):
                    args = self.parse_args()
                    expr = N.MethodCall(span=self.span_from(expr.span), obj=expr, method=name.value,
                                        method_span=name.span, args=args)
                else:
                    expr = N.FieldAccess(span=self.span_from(expr.span), obj=expr, name=name.value,
                                         name_span=name.span)
            elif self.at_op("?"):
                self.advance()
                expr = N.Try(span=self.span_from(expr.span), expr=expr)
            elif self.at_kw("with"):
                self.advance()
                fields = self.parse_field_inits()
                expr = N.WithExpr(span=self.span_from(expr.span), base=expr, fields=fields)
            elif self.at_op("["):
                self.fail("indexing with `[]` is not supported", hint="use `.get(i)` which returns `Option[T]` (Some/None)")
            else:
                return expr

    def parse_field_inits(self) -> List[N.FieldInit]:
        self.expect_op("{")
        old = self.no_struct
        self.no_struct = False
        fields = []
        self.skip_nl()
        while not self.at_op("}"):
            tok = self.expect_ident("field name")
            if not self.accept_op(":"):
                self.fail(f"expected `:` after field `{tok.value}`",
                          hint=f"write `{tok.value}: value` (no shorthand fields in Klar)")
            value = self.parse_expr()
            fields.append(N.FieldInit(span=self.span_from(tok.span), name=tok.value, value=value))
            self.accept_op(",")
            self.skip_nl()
        self.expect_op("}")
        self.no_struct = old
        return fields

    def parse_primary(self):
        tok = self.cur
        start = tok.span
        if tok.kind == "INT":
            self.advance()
            return N.IntLit(span=start, value=tok.value)
        if tok.kind == "FLOAT":
            self.advance()
            return N.FloatLit(span=start, value=tok.value)
        if tok.kind == "STR":
            self.advance()
            return self.string_node(tok)
        if tok.kind == "KW":
            if tok.value in ("true", "false"):
                self.advance()
                return N.BoolLit(span=start, value=(tok.value == "true"))
            if tok.value == "match":
                return self.parse_match()
            if tok.value == "fn":
                return self.parse_lambda()
            if tok.value == "if":
                self.fail("`if` is a statement, not an expression",
                          hint="to choose a value use `match cond { true => a, false => b }`")
        if tok.kind == "OP":
            if tok.value == "(":
                self.advance()
                if self.accept_op(")"):
                    return N.UnitLit(span=self.span_from(start))
                old = self.no_struct
                self.no_struct = False
                e = self.parse_expr()
                self.no_struct = old
                if self.at_op(","):
                    self.fail("tuples are not supported in Klar 0.1", hint="define a record type with named fields")
                self.expect_op(")")
                return e
            if tok.value == "[":
                self.advance()
                old = self.no_struct
                self.no_struct = False
                items = []
                self.skip_nl()
                while not self.at_op("]"):
                    items.append(self.parse_expr())
                    self.skip_nl()
                    if not self.accept_op(","):
                        break
                    self.skip_nl()
                self.expect_op("]", " to close the list")
                self.no_struct = old
                return N.ListLit(span=self.span_from(start), items=items)
        if tok.kind == "IDENT":
            self.advance()
            if tok.value[:1].isupper() and self.at_op("{") and not self.no_struct:
                if tok.value == "Map":
                    return self.parse_map_lit(tok)
                fields = self.parse_field_inits()
                return N.RecordLit(span=self.span_from(start), type_name=tok.value, fields=fields)
            if tok.value in ("null", "nil", "undefined"):
                self.fail(f"Klar has no `{tok.value}`", tok=tok, hint="use `Option[T]`: `None` / `Some(value)`",
                          code="E0201", fix={"span": tok.span, "text": "None"})
            return N.Name(span=start, name=tok.value)
        hint = None
        if tok.kind == "OP" and tok.value in ("+", "*", "/", "%", "==", "!=", "<", ">", "<=", ">=", "and", "or", "."):
            hint = (f"a line cannot start with `{tok.value}`: to continue an expression on the next line, "
                    f"end the previous line with the operator")
        self.fail(f"expected an expression, found {tok.describe()}", hint=hint)

    def string_node(self, tok: Token) -> N.StrLit:
        parts = []
        for p in tok.parts or []:
            if isinstance(p, str):
                parts.append(p)
            else:
                _, text, line, col = p
                sub = Parser(tokenize(text, self.file, line, col), self.file)
                parts.append(sub.parse_standalone_expr())
        return N.StrLit(span=tok.span, parts=parts)

    def parse_standalone_expr(self):
        e = self.parse_expr()
        self.skip_nl()
        if not self.at("EOF"):
            self.fail(f"unexpected {self.cur.describe()} in interpolation")
        return e

    def parse_map_lit(self, tok) -> N.MapLit:
        self.expect_op("{")
        old = self.no_struct
        self.no_struct = False
        entries = []
        self.skip_nl()
        while not self.at_op("}"):
            k = self.parse_expr()
            self.expect_op(":", " between map key and value")
            v = self.parse_expr()
            entries.append(N.MapEntry(span=k.span.merge(v.span), key=k, value=v))
            self.accept_op(",")
            self.skip_nl()
        self.expect_op("}")
        self.no_struct = old
        return N.MapLit(span=self.span_from(tok.span), entries=entries)

    def parse_match(self) -> N.Match:
        start = self.advance().span
        subject = self.parse_expr_ns()
        self.skip_nl()
        self.expect_op("{", " to start match arms")
        old = self.no_struct
        self.no_struct = False
        arms = []
        self.skip_nl()
        while not self.at_op("}"):
            pat = self.parse_pattern()
            guard = None
            if self.accept_kw("if"):
                guard = self.parse_expr_ns()
            if self.at_op("->") or self.at_op(":"):
                self.fail("match arms use `=>`", hint="write `pattern => value`")
            self.expect_op("=>", " after pattern")
            if self.at_op("{"):
                body = self.parse_block()
            else:
                body = self.parse_expr()
            arms.append(N.MatchArm(span=pat.span.merge(body.span), pattern=pat, guard=guard, body=body))
            self.accept_op(",")
            self.skip_nl()
        self.expect_op("}")
        self.no_struct = old
        if not arms:
            self.fail("match needs at least one arm", tok=self.prev())
        return N.Match(span=self.span_from(start), subject=subject, arms=arms)

    def parse_pattern(self):
        tok = self.cur
        start = tok.span
        if tok.kind == "IDENT" and tok.value == "_":
            self.advance()
            return N.PWild(span=start)
        if tok.kind == "INT" or tok.kind == "FLOAT":
            self.advance()
            return N.PLit(span=start, value=tok.value)
        if tok.kind == "OP" and tok.value == "-" and self.peek().kind in ("INT", "FLOAT"):
            self.advance()
            num = self.advance()
            return N.PLit(span=self.span_from(start), value=-num.value)
        if tok.kind == "STR":
            if any(not isinstance(p, str) for p in (tok.parts or [])):
                self.fail("interpolated strings cannot be patterns")
            self.advance()
            return N.PLit(span=start, value=tok.value)
        if tok.kind == "KW" and tok.value in ("true", "false"):
            self.advance()
            return N.PLit(span=start, value=(tok.value == "true"))
        if tok.kind == "IDENT":
            self.advance()
            name = tok.value
            if name in ("Some", "Ok", "Err"):
                self.expect_op("(", f" after `{name}` in pattern", hint=f"write `{name}(x)`")
                inner = self.parse_pattern()
                self.expect_op(")")
                return N.PVariant(span=self.span_from(start), enum=None, variant=name, args=[inner])
            if name == "None":
                return N.PVariant(span=start, enum=None, variant="None", args=[])
            if name[:1].isupper():
                if not self.at_op("."):
                    self.fail(f"enum variants in patterns must be qualified: `EnumName.{name}`", tok=tok,
                              hint=f"write `MyEnum.{name}`")
                self.advance()
                vtok = self.expect_ident("variant name")
                args = []
                if self.accept_op("("):
                    while not self.at_op(")"):
                        args.append(self.parse_pattern())
                        if not self.accept_op(","):
                            break
                    self.expect_op(")")
                return N.PVariant(span=self.span_from(start), enum=name, variant=vtok.value, args=args)
            return N.PBind(span=start, name=name)
        self.fail(f"expected a pattern, found {tok.describe()}",
                  hint="patterns: `_`, `name`, literals, `Some(x)`, `None`, `Ok(x)`, `Err(e)`, `Enum.Variant(a, b)`")

    def parse_lambda(self) -> N.Lambda:
        start = self.advance().span  # fn
        if self.at("IDENT"):
            self.fail("named functions cannot be declared inside blocks",
                      hint="declare it at top level, or use a lambda: `let f = fn(x: Int) => x * 2`")
        self.expect_op("(", " after `fn`")
        params = self.parse_params(require_types=False)
        self.expect_op(")")
        ret = None
        if self.accept_op("->"):
            ret = self.parse_type()
        old = self.no_struct
        self.no_struct = False
        if self.at_op("=>"):
            arrow = self.advance()
            if self.at_op("{"):
                self.fail("a lambda with a block body has no `=>`", tok=arrow,
                          hint="write `fn(x) { return value }` (statements on their own lines), or keep `=>` with one expression: "
                               "`fn(x) => x * 2`",
                          fix={"span": Span(arrow.span.file, arrow.span.line, arrow.span.col,
                                            self.cur.span.line, self.cur.span.col), "text": ""})
            body = self.parse_expr()
        elif self.at_op("{"):
            body = self.parse_block()
        else:
            self.fail("expected `=>` or `{` after lambda parameters",
                      hint="write `fn(x) => x + 1` or `fn(x: Int) -> Int { return x + 1 }`")
        self.no_struct = old
        return N.Lambda(span=self.span_from(start), params=params, ret=ret, body=body)


def parse(src: str, file: str) -> N.Program:
    return Parser(tokenize(src, file), file).parse_program()


def parse_signature(sig: str) -> N.FnDecl:
    """Parse a body-less signature (used for built-ins)."""
    p = Parser(tokenize(sig, "<builtin>"), "<builtin>")
    return p.parse_fn(with_body=False)
