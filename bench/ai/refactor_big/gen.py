#!/usr/bin/env python3
"""Builds the large refactoring task b1_shop: one program in Klar and Python, its reference change and its checks.

    python bench/ai/refactor_big/gen.py [--entities N]

`src/shop.*.in` holds the modules the change touches; `«old¦new»` marks what differs between the original program and
the reference. The other modules are the same template over different records: they never need to change and they make
the program too long to keep in mind. `src/checks.txt` holds the checks, one text for both languages. The output goes
to `b1_shop/`, the layout of bench/ai/refactor_bench.py, with the Klar files through `klar fmt`.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(HERE, "b1_shop")
MARK = re.compile(r"«(.*?)¦(.*?)»", re.S)

# module, type, int field, float field (operating figures, which the change leaves alone), three kinds
ENTITIES = [
    ("warehouses", "Warehouse", "bays", "rent", ("Central", "Regional", "Overflow")),
    ("suppliers", "Supplier", "lead_days", "rating", ("Maker", "Reseller", "Importer")),
    ("carriers", "Carrier", "vans", "fuel_cost", ("Road", "Rail", "Courier")),
    ("campaigns", "Campaign", "clicks", "budget", ("Email", "Banner", "Radio")),
    ("employees", "Employee", "shifts", "wage", ("Picker", "Driver", "Clerk")),
    ("routes", "Route", "stops", "distance", ("Urban", "Rural", "Express")),
    ("shelves", "Shelf", "slots", "height", ("Open", "Cold", "Locked")),
    ("tickets", "Ticket", "replies", "hours", ("Question", "Complaint", "Request")),
    ("contracts", "Contract", "months", "fee", ("Lease", "Service", "Licence")),
    ("machines", "Machine", "cycles", "power", ("Press", "Scanner", "Lift")),
    ("branches", "Branch", "desks", "floor_area", ("Shop", "Office", "Depot")),
    ("partners", "Partner", "referrals", "share", ("Reseller", "Affiliate", "Agent")),
    ("assets", "Asset", "age_years", "book_value", ("Vehicle", "Fixture", "Device")),
    ("audits", "Inspection", "findings", "duration", ("Safety", "Stock", "Tax")),
]

KLAR_ENTITY = """/// The kinds of @t@ records.
pub enum @T@Kind {
  @A@
  @B@
  @C@
}

pub type @T@ {
  id: Int
  name: Str
  city: Str
  kind: @T@Kind
  @i@: Int
  @f@: Float
  active: Bool
}

/// The record with this id.
pub fn @m@_find(xs: List[@T@], id: Int) -> Option[@T@] {
  return xs.find(fn(x) => x.id == id)
}

/// The records of one city.
pub fn @m@_in_city(xs: List[@T@], city: Str) -> List[@T@] {
  return xs.filter(fn(x) => x.city == city)
}

/// The records in use.
pub fn @m@_active(xs: List[@T@]) -> List[@T@] {
  return xs.filter(fn(x) => x.active)
}

/// The names, in order.
pub fn @m@_names(xs: List[@T@]) -> List[Str] {
  return xs.map(fn(x) => x.name).sort()
}

/// The sum of @i@.
pub fn @m@_total_@i@(xs: List[@T@]) -> Int {
  return xs.map(fn(x) => x.@i@).sum()
}

/// The sum of @f@.
pub fn @m@_total_@f@(xs: List[@T@]) -> Float {
  return xs.map(fn(x) => x.@f@).sum_float()
}

/// The mean of @f@, 0 for no records.
pub fn @m@_average_@f@(xs: List[@T@]) -> Float {
  if xs.is_empty() {
    return 0.0
  }
  return @m@_total_@f@(xs) / xs.len().to_float()
}

/// The kind as people read it.
pub fn @m@_kind_label(k: @T@Kind) -> Str {
  return match k {
    @T@Kind.@A@ => "@A@",
    @T@Kind.@B@ => "@B@",
    @T@Kind.@C@ => "@C@",
  }
}

/// How much a kind counts in a score.
pub fn @m@_kind_weight(k: @T@Kind) -> Float {
  return match k {
    @T@Kind.@A@ => 1.0,
    @T@Kind.@B@ => 1.5,
    @T@Kind.@C@ => 2.0,
  }
}

/// One record as text.
pub fn @m@_describe(x: @T@) -> Str {
  return "{x.name} ({x.city}), {@m@_kind_label(x.kind)}: {x.@i@} @i@, {x.@f@.fixed(2)} @f@"
}

/// The records of one kind.
pub fn @m@_by_kind(xs: List[@T@], k: @T@Kind) -> List[@T@] {
  return xs.filter(fn(x) => x.kind == k)
}

/// The records with the most @i@ first.
pub fn @m@_ranked(xs: List[@T@]) -> List[@T@] {
  return xs.sort_by(fn(x) => 0 - x.@i@)
}

/// The first few of the ranking.
pub fn @m@_top(xs: List[@T@], n: Int) -> List[@T@] {
  return @m@_ranked(xs).take(n)
}

/// What is wrong with a record.
pub fn @m@_validate(x: @T@) -> List[Str] {
  var errors: List[Str] = []
  if x.name.is_empty() {
    errors = errors.push("no name")
  }
  if x.city.is_empty() {
    errors = errors.push("no city")
  }
  if x.@i@ < 0 {
    errors = errors.push("negative @i@")
  }
  if x.@f@ < 0.0 {
    errors = errors.push("negative @f@")
  }
  return errors
}

/// The record with @f@ and @i@ weighed together.
pub fn @m@_score(x: @T@) -> Float {
  return x.@f@ * @m@_kind_weight(x.kind) + x.@i@.to_float()
}

/// A row of the export file.
pub fn @m@_row(x: @T@) -> Str {
  return "{x.id},{x.name},{x.city},{@m@_kind_label(x.kind)},{x.@i@},{x.@f@.fixed(2)}"
}

/// The export file.
pub fn @m@_file(xs: List[@T@]) -> Str {
  return ["id,name,city,kind,@i@,@f@"].concat(xs.map(fn(x) => @m@_row(x))).join("\\n")
}

/// The number of records per city.
pub fn @m@_per_city(xs: List[@T@]) -> Map[Str, Int] {
  var m: Map[Str, Int] = Map {}
  for x in xs {
    m = m.update(x.city, 0, fn(v) => v + 1)
  }
  return m
}

/// The records above a limit of @f@.
pub fn @m@_over(xs: List[@T@], limit: Float) -> List[@T@] {
  return xs.filter(fn(x) => x.@f@ > limit)
}

/// A line for the dashboard.
pub fn @m@_summary(xs: List[@T@]) -> Str {
  return "{xs.len()} @t@ records, {@m@_active(xs).len()} active, {@m@_total_@f@(xs).fixed(2)} @f@"
}
"""

PY_ENTITY = """from dataclasses import dataclass
from enum import Enum


class @T@Kind(Enum):
    \"\"\"The kinds of @t@ records.\"\"\"
    @AU@ = "@A@"
    @BU@ = "@B@"
    @CU@ = "@C@"


@dataclass(frozen=True)
class @T@:
    id: int
    name: str
    city: str
    kind: @T@Kind
    @i@: int
    @f@: float
    active: bool


def @m@_find(xs: list[@T@], id: int) -> @T@ | None:
    \"\"\"The record with this id.\"\"\"
    return next((x for x in xs if x.id == id), None)


def @m@_in_city(xs: list[@T@], city: str) -> list[@T@]:
    \"\"\"The records of one city.\"\"\"
    return [x for x in xs if x.city == city]


def @m@_active(xs: list[@T@]) -> list[@T@]:
    \"\"\"The records in use.\"\"\"
    return [x for x in xs if x.active]


def @m@_names(xs: list[@T@]) -> list[str]:
    \"\"\"The names, in order.\"\"\"
    return sorted(x.name for x in xs)


def @m@_total_@i@(xs: list[@T@]) -> int:
    \"\"\"The sum of @i@.\"\"\"
    return sum(x.@i@ for x in xs)


def @m@_total_@f@(xs: list[@T@]) -> float:
    \"\"\"The sum of @f@.\"\"\"
    return sum(x.@f@ for x in xs)


def @m@_average_@f@(xs: list[@T@]) -> float:
    \"\"\"The mean of @f@, 0 for no records.\"\"\"
    if not xs:
        return 0.0
    return @m@_total_@f@(xs) / len(xs)


def @m@_kind_label(k: @T@Kind) -> str:
    \"\"\"The kind as people read it.\"\"\"
    return k.value


def @m@_kind_weight(k: @T@Kind) -> float:
    \"\"\"How much a kind counts in a score.\"\"\"
    match k:
        case @T@Kind.@AU@:
            return 1.0
        case @T@Kind.@BU@:
            return 1.5
        case @T@Kind.@CU@:
            return 2.0


def @m@_describe(x: @T@) -> str:
    \"\"\"One record as text.\"\"\"
    return f"{x.name} ({x.city}), {@m@_kind_label(x.kind)}: {x.@i@} @i@, {x.@f@:.2f} @f@"


def @m@_by_kind(xs: list[@T@], k: @T@Kind) -> list[@T@]:
    \"\"\"The records of one kind.\"\"\"
    return [x for x in xs if x.kind == k]


def @m@_ranked(xs: list[@T@]) -> list[@T@]:
    \"\"\"The records with the most @i@ first.\"\"\"
    return sorted(xs, key=lambda x: -x.@i@)


def @m@_top(xs: list[@T@], n: int) -> list[@T@]:
    \"\"\"The first few of the ranking.\"\"\"
    return @m@_ranked(xs)[:n]


def @m@_validate(x: @T@) -> list[str]:
    \"\"\"What is wrong with a record.\"\"\"
    errors = []
    if not x.name:
        errors.append("no name")
    if not x.city:
        errors.append("no city")
    if x.@i@ < 0:
        errors.append("negative @i@")
    if x.@f@ < 0.0:
        errors.append("negative @f@")
    return errors


def @m@_score(x: @T@) -> float:
    \"\"\"The record with @f@ and @i@ weighed together.\"\"\"
    return x.@f@ * @m@_kind_weight(x.kind) + x.@i@


def @m@_row(x: @T@) -> str:
    \"\"\"A row of the export file.\"\"\"
    return f"{x.id},{x.name},{x.city},{@m@_kind_label(x.kind)},{x.@i@},{x.@f@:.2f}"


def @m@_file(xs: list[@T@]) -> str:
    \"\"\"The export file.\"\"\"
    return "\\n".join(["id,name,city,kind,@i@,@f@", *(@m@_row(x) for x in xs)])


def @m@_per_city(xs: list[@T@]) -> dict[str, int]:
    \"\"\"The number of records per city.\"\"\"
    m: dict[str, int] = {}
    for x in xs:
        m[x.city] = m.get(x.city, 0) + 1
    return m


def @m@_over(xs: list[@T@], limit: float) -> list[@T@]:
    \"\"\"The records above a limit of @f@.\"\"\"
    return [x for x in xs if x.@f@ > limit]


def @m@_summary(xs: list[@T@]) -> str:
    \"\"\"A line for the dashboard.\"\"\"
    return f"{len(xs)} @t@ records, {len(@m@_active(xs))} active, {@m@_total_@f@(xs):.2f} @f@"
"""

KLAR_HELPERS = """fn prodc(price: Int, category: Category) -> Product {
  return Product { sku: "S", name: "item", price: price, weight: 1.0, category: category, stock: 2, supplier: 1 }
}

fn prod(price: Int) -> Product {
  return Product { sku: "P", name: "item", price: price, weight: 1.0, category: Category.Book, stock: 2, supplier: 1 }
}

fn ln(price: Int, qty: Int) -> Line {
  return Line { sku: "S", qty: qty, unit_price: price }
}

fn ord(status: Status, items: List[Line], sent: Int) -> Order {
  return Order { id: 1, customer: 1, lines: items, status: status, shipping: sent, day: 1 }
}

fn cust(first: Str, last: Str) -> Customer {
  return Customer { id: 1, first_name: first, last_name: last, email: "a@b.org", tier: Tier.Basic, city: "Harbour" }
}

fn custt(tier: Tier) -> Customer {
  return Customer { id: 1, first_name: "Ada", last_name: "Lovelace", email: "a@b.org", tier: tier, city: "Harbour" }
}

fn size[T](xs: List[T]) -> Int {
  return xs.len()
}

fn mget(m: Map[Str, Int], key: Str) -> Int {
  return m.get(key).unwrap_or(-1)
}

fn names(cs: List[Customer]) -> List[Str] {
  return cs.map(fn(c) => "{c.first_name} {c.last_name}")
}
"""

PY_HELPERS = """def prodc(price: int, category: Category) -> Product:
    return Product("S", "item", price, 1.0, category, 2, 1)


def prod(price: int) -> Product:
    return Product("P", "item", price, 1.0, Category.BOOK, 2, 1)


def ln(price: int, qty: int) -> Line:
    return Line("S", qty, price)


def ord(status: Status, items: list[Line], sent: int) -> Order:
    return Order(1, 1, items, status, sent, 1)


def cust(first: str, last: str) -> Customer:
    return Customer(1, first, last, "a@b.org", Tier.BASIC, "Harbour")


def custt(tier: Tier) -> Customer:
    return Customer(1, "Ada", "Lovelace", "a@b.org", tier, "Harbour")


def size(xs: list[Any]) -> int:
    return len(xs)


def mget(m: dict[str, int], key: str) -> int:
    return m.get(key, -1)


def names(cs: list[Customer]) -> list[str]:
    return [f"{c.first_name} {c.last_name}" for c in cs]


def Some(x: Any) -> Any:
    return x


passed = 0
failed = 0


def equal(actual: Any, expected: Any) -> None:
    if actual != expected:
        raise AssertionError(f"got {actual!r}, expected {expected!r}")


def run(name: str, test: Callable[[], None]) -> None:
    global passed, failed
    try:
        test()
        passed += 1
    except Exception as e:  # a crash is a failed check, not the end of the run
        failed += 1
        print(f"FAIL  {name}{chr(10)}      {type(e).__name__}: {e}")


"""


def split(path):
    """{module: text} of a `#### module` file."""
    with open(path, encoding="utf-8") as f:
        parts = re.split(r"(?m)^#### (\w+)\n", f.read())
    return dict(zip(parts[1::2], parts[2::2]))


def side(text, which):
    return MARK.sub(lambda m: m.group(which), text)


def entity(template, row):
    m, t, i, f, kinds = row
    text = template
    for a, b in {"@m@": m, "@T@": t, "@t@": t.lower(), "@i@": i, "@f@": f, "@A@": kinds[0], "@B@": kinds[1], "@C@": kinds[2],
                 "@AU@": kinds[0].upper(), "@BU@": kinds[1].upper(), "@CU@": kinds[2].upper()}.items():
        text = text.replace(a, b)
    return text


def main_module(lang, rows):
    with open(os.path.join(HERE, "src", "main.klar.in" if lang == "klar" else "main.py.in"), encoding="utf-8") as f:
        text = f.read()
    if lang == "klar":
        uses = "\n".join(f"use {r[0]}.{{{r[0]}_summary}}" for r in rows)
        calls = "\n".join(f"  print({r[0]}_summary([]))" for r in rows)
    else:
        uses = "\n".join(f"from {r[0]} import {r[0]}_summary" for r in rows)
        calls = "\n".join(f"    print({r[0]}_summary([]))" for r in rows)
    return text.replace("@USES@", uses).replace("@CALLS@", calls)


def load_checks():
    checks = []
    with open(os.path.join(HERE, "src", "checks.txt"), encoding="utf-8") as f:
        for line in f:
            line = line.rstrip()
            if not line or line.startswith("#"):
                continue
            if not line.startswith(" "):
                kind, name = line.split(" ", 1)
                checks.append((kind, name, []))
            else:
                actual, expected = line.strip().split(" == ", 1)
                checks[-1][2].append((actual, expected))
    return checks


def public_names(modules, lang):
    """{name: module} of what a test can import."""
    pat = re.compile(r"(?m)^pub (?:fn|const) (\w+)" if lang == "klar" else r"(?m)^def (\w+)")
    return {n: m for m, text in modules.items() for n in pat.findall(text)}


def to_python(text):
    text = re.sub(r"\b(Status|Tier|Category)\.(\w+)", lambda m: f"{m.group(1)}.{re.sub(r'(?<!^)(?=[A-Z])', '_', m.group(2)).upper()}", text)
    return re.sub(r"\btrue\b", "True", re.sub(r"\bfalse\b", "False", text))


def imports(checks, table):
    """{module: sorted names} that the checks use."""
    text = " ".join(a + " " + e for _, _, lines in checks for a, e in lines)
    used = {}
    for n in set(re.findall(r"\b[a-z_]\w*\b(?=\()", text)):
        if n in table:
            used.setdefault(table[n], set()).add(n)
    return {m: sorted(ns) for m, ns in sorted(used.items())}


def klar_checks(checks, table):
    head = ["use model.{Product, Customer, Line, Order, Status, Tier, Category}"]
    head += [f"use {m}.{{{', '.join(ns)}}}" for m, ns in imports(checks, table).items()]
    body = ["\n".join(head), "", KLAR_HELPERS]
    for _, name, lines in checks:
        body.append(f'test "{name}" {{\n' + "\n".join(f"  assert {a} == {e}" for a, e in lines) + "\n}\n")
    return "\n".join(body)


def python_checks(checks, table):
    head = ["import sys", "from typing import Any, Callable", "", "from model import Category, Customer, Line, Order, Product, Status, Tier"]
    head += [f"from {m} import {', '.join(ns)}" for m, ns in imports(checks, table).items()]
    body = ["\n".join(head), "", "", PY_HELPERS]
    for n, (_, name, lines) in enumerate(checks):
        body.append(f"def check_{n}() -> None:\n" + "\n".join(f"    equal({to_python(a)}, {to_python(e)})" for a, e in lines) + "\n\n")
        body.append(f'run("{name}", check_{n})\n\n')
    body.append('print(f"{passed} passed, {failed} failed")\nsys.exit(1 if failed else 0)\n')
    return "\n".join(body)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text.rstrip("\n") + "\n")


def build(entities):
    rows = ENTITIES[:entities]
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    checks = load_checks()
    for lang, ext, src, template in (("klar", ".klar", "shop.klar.in", KLAR_ENTITY), ("python", ".py", "shop.py.in", PY_ENTITY)):
        modules = split(os.path.join(HERE, "src", src))
        modules["main"] = main_module(lang, rows)
        modules.update({r[0]: entity(template, r) for r in rows})
        for m, text in modules.items():
            old, new = side(text, 1), side(text, 2)
            write(os.path.join(OUT, lang, m + ext), old)
            if old != new:
                write(os.path.join(OUT, "ref", lang, m + ext), new)
        table = public_names({m: side(t, 2) for m, t in modules.items()}, lang)
        for kind in ("visible", "holdout"):
            chosen = [c for c in checks if c[0] == kind]
            text = klar_checks(chosen, table) if lang == "klar" else python_checks(chosen, table)
            write(os.path.join(OUT, "tests", ("check" if kind == "visible" else "holdout") + ext), text)
    for sub in ("klar", os.path.join("ref", "klar"), "tests"):
        d = os.path.join(OUT, sub)
        for f in sorted(os.listdir(d)):
            if f.endswith(".klar"):
                subprocess.run([sys.executable, "-m", "klar", "fmt", os.path.join(d, f)], cwd=ROOT, capture_output=True)
    shutil.copy(os.path.join(HERE, "src", "task.md"), os.path.join(OUT, "task.md"))
    counts = {k: sum(1 for c in checks if c[0] == k) for k in ("visible", "holdout")}
    print(f"{len(rows)} template modules, checks {counts}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--entities", type=int, default=len(ENTITIES))
    build(ap.parse_args().entities)
