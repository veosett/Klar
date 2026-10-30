"""The checks of b2_compiler: programs, commands and what must come out. The same for both implementations of Klar."""

PRELUDE = """fn double(x: Int) -> Int {
  return x * 2
}

fn add(a: Int, b: Int) -> Int {
  return a + b
}

fn id[T](x: T) -> T {
  return x
}

fn total(xs: List[Int]) -> Int {
  return xs.sum()
}

fn half(x: Int) -> Option[Int] {
  if x % 2 != 0 {
    return None
  }
  return Some(x / 2)
}

fn tick(x: Int) -> Int uses io {
  print(x)
  return x
}

fn flag(b: Bool) -> Str {
  return match b {
    true => "yes",
    false => "no",
  }
}

"""


def run(name, kind, main, out, extra=""):
    """`main`'s body runs and prints `out`."""
    body = "\n".join("  " + line for line in main.split("\n"))
    src = f"{PRELUDE}{extra}fn main() uses io {{\n{body}\n}}\n"
    return dict(name=name, kind=kind, src=src, cmd=["run", "p.klar"], code=0, out=out)


def codes(name, kind, main, has, lacks=(), extra="", fail=True):
    """`klar check` reports `has` and not `lacks`."""
    body = "\n".join("  " + line for line in main.split("\n"))
    src = f"{PRELUDE}{extra}fn main() uses io {{\n{body}\n}}\n"
    return dict(name=name, kind=kind, src=src, cmd=["check", "p.klar"], code=1 if fail else 0, has=list(has), lacks=list(lacks))


SMALL = """fn double(x: Int) -> Int {
  return x * 2
}

fn plus(a: Int, b: Int) -> Int {
  return a + b
}

fn main() uses io {
  let y = 3
  print(y |> plus(4) |> double())
}

test "t" {
  assert (1 |> double()) == 2
}
"""

CHECKS = [
    # running
    run("run: one pipe", "visible", "print(3 |> double())", "6\n"),
    run("run: a chain", "visible", "print(3 |> add(4) |> double())", "14\n"),
    run("run: continued lines", "visible", "let v = 3\n  |> add(4)\n  |> double()\nprint(v)", "14\n"),
    run("run: looser than arithmetic", "holdout", "print(1 + 2 |> double())", "6\n"),
    run("run: looser than or", "holdout", 'print(false or true |> flag())', "yes\n"),
    run("run: parentheses", "holdout", "print((3 |> double()) + 1)", "7\n"),
    run("run: generic", "visible", 'print(3 |> id())\nprint("a" |> id())', "3\na\n"),
    run("run: named argument", "holdout", "print(3 |> add(b: 4))", "7\n"),
    run("run: interpolation", "holdout", 'print("got {3 |> double()}")', "got 6\n"),
    run("run: condition and match", "holdout",
        'if (2 |> double()) == 4 {\n  print("four")\n}\nlet s = match 3 |> double() {\n  6 => "six",\n  _ => "other",\n}\nprint(s)',
        "four\nsix\n"),
    run("run: in a lambda", "visible", "print([1, 2].map(fn(n) => n |> double()))", "[2, 4]\n"),
    run("run: a list keeps its owner", "holdout", "let xs = [1, 2]\nprint(xs |> total())\nprint(xs.len())", "3\n2\n"),
    run("run: order of evaluation", "holdout", "print(tick(1) |> add(tick(2)))", "1\n2\n3\n"),
    run("run: question mark", "holdout", 'match both(8) {\n  Some(v) => print(v),\n  None => print("none"),\n}', "2\n",
        extra="fn both(x: Int) -> Option[Int] {\n  let a = (x |> half())?\n  return a |> half()\n}\n\n"),
    # the checker
    codes("check: right side not a call", "visible", "print(3 |> 4)", ["E0225", "the right side of `|>` must be a call"]),
    codes("check: right side a method", "holdout", 'let x = "a"\nprint(3 |> x.len())', ["E0225"]),
    codes("check: right side a name", "holdout", "print(3 |> double)", ["E0225"]),
    codes("check: wrong type", "visible", 'print("a" |> double())', ["E0202"]),
    codes("check: missing argument", "holdout", "print(3 |> add())", ["E0206"]),
    codes("check: unknown function", "holdout", "print(3 |> nothing())", ["E0201"]),
    codes("check: missing effect", "visible", "print(pure_one(1))", ["E0401"],
          extra="fn pure_one(x: Int) -> Int {\n  return x |> tick()\n}\n\n"),
    codes("check: unused value", "holdout", "3 |> double()", ["W0401"], fail=False),
    codes("check: discarded Result", "holdout", "3 |> risky()", ["E0402"],
          extra="fn risky(x: Int) -> Result[Int, Str] {\n  return Ok(x)\n}\n\n"),
    codes("check: variable used only in a pipe", "visible", "let y = 3\nlet z = 4\nprint(y |> add(z))", [], ["W0402"], fail=False),
    codes("check: function used only in a pipe", "visible", "print(1 |> only())", [], ["function `only` is never used"], fail=False,
          extra="fn only(x: Int) -> Int {\n  return x\n}\n\n"),
    codes("check: broken requires", "holdout", "print(4 |> div(0))", ["E0703"],
          extra="fn div(a: Int, b: Int) -> Int\n  requires b != 0\n{\n  return a / b\n}\n\n"),
    codes("check: division that may be by zero", "holdout", "print(zero(1, 0))", ["E0701"],
          extra="fn zero(a: Int, b: Int) -> Int {\n  return (a |> double()) / (b |> double())\n}\n\n"),
    codes("check: lambda that captures a var", "holdout", "var n = 1\nn = 2\nprint([1].map(fn(k) => n |> add(k)))", ["E0216"]),
    # running through other commands
    dict(name="test: a test with a pipe", kind="visible", src=PRELUDE + 'test "t" {\n  assert (3 |> double()) == 6\n}\n',
         cmd=["test", "p.klar"], code=0, has=["1 passed, 0 failed"]),
    dict(name="test: a failing pipe", kind="holdout", src=PRELUDE + 'test "t" {\n  assert (3 |> double()) == 7\n}\n',
         cmd=["test", "p.klar"], code=1, has=["0 passed, 1 failed"]),
    dict(name="test: a doc-test", kind="holdout", src="/// >>> assert (2 |> twice()) == 4\npub fn twice(x: Int) -> Int {\n  return x * 2\n}\n",
         cmd=["test", "p.klar"], code=0, has=["1 passed, 0 failed"]),
    dict(name="eval: a pipe", kind="visible", cmd=["eval", "3 |> Some()"], code=0, has=["Some(3)"]),
    # the tree
    dict(name="ast: a node of its own", kind="visible", src="fn main() uses io {\n  print(3 |> f(4))\n}\n", cmd=["ast", "p.klar"], code=0,
         has=['"node": "Pipe"', '"value": {"node": "IntLit"', '"call": {"node": "Call"']),
    dict(name="ast: the call is as written", kind="holdout", src="fn main() uses io {\n  print(3 |> f(4))\n}\n", cmd=["ast", "p.klar"], code=0,
         has=['"args": [{"node": "Arg"']),
    # the formatter
    dict(name="fmt: spaces", kind="visible", src="fn main() uses io {\n  print(3|>f(4)  |>g())\n}\n", cmd=["fmt", "p.klar"],
         after="fn main() uses io {\n  print(3 |> f(4) |> g())\n}\n"),
    dict(name="fmt: parentheses that matter", kind="holdout", src="fn main() uses io {\n  print((3 |> f()) + 1)\n  print(1 + 3 |> f())\n}\n",
         cmd=["fmt", "p.klar"], code=0, after="fn main() uses io {\n  print((3 |> f()) + 1)\n  print(1 + 3 |> f())\n}\n"),
    dict(name="fmt: continued lines join", kind="holdout", src="fn main() uses io {\n  let v = 3\n    |> f()\n  print(v)\n}\n", cmd=["fmt", "p.klar"],
         after="fn main() uses io {\n  let v = 3 |> f()\n  print(v)\n}\n"),
    # the tools
    dict(name="refs: the function on the right", kind="visible", src=SMALL, cmd=["refs", "p.klar", "double"], code=0,
         has=["p.klar:11:", "p.klar:15:"]),
    dict(name="refs: the variable on the left", kind="holdout", src=SMALL, cmd=["refs", "p.klar", "y"], code=0, has=["p.klar:11:"]),
    dict(name="rename: the function", kind="visible", src=SMALL, cmd=["rename", "p.klar", "double", "twice"],
         after_has=["y |> plus(4) |> twice()", "(1 |> twice()) == 2", "fn twice("], after_lacks=["double"]),
    dict(name="rename: the variable", kind="holdout", src=SMALL, cmd=["rename", "p.klar", "y", "start"],
         after_has=["let start = 3", "start |> plus(4)"]),
    dict(name="context: a pipe is a call", kind="holdout", src=SMALL, cmd=["context", "p.klar", "plus"], code=0, has=["main"]),
    dict(name="coverage: through a pipe", kind="visible", src=SMALL.replace("fn main() uses io {\n  let y = 3\n  print(y |> plus(4) |> double())\n}\n\n", "")
         .replace("assert (1 |> double()) == 2", "assert (1 |> plus(1) |> double()) == 4"), cmd=["coverage", "p.klar"], code=0, has=["100.0%"]),
    dict(name="explain: the new code", kind="holdout", cmd=["explain", "E0225"], code=0, has=["|>"]),
]
