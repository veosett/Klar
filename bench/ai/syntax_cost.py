#!/usr/bin/env python3
"""What the length of the agents' Klar solutions is made of: a static estimate, no model is called.

    python bench/ai/syntax_cost.py

For each candidate change of the syntax it rewrites the last answer of every recorded agent run and counts the
tokens saved, and it counts how many solutions import a std module. Tokens: a name, a number, a string or a
punctuation mark is one, close to how tokenizers cut code. It says nothing about errors or retries: those need a
run with agents (item 21 of docs/ROADMAP.md).
"""
import glob
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|[A-Za-z_][A-Za-z_0-9]*|\d+|==|!=|<=|>=|->|=>|\S')
GET = re.compile(r"match (\w+)\.get\(([^()]*)\) \{\s*Some\((\w+)\) => (?:\{\s*return \3\s*\}|\3),?\s*None => "
                 r"(?:\{\s*return ([^{}\n]+?)\s*\}|([^{}\n]+?)),?\s*\}")

CHANGES = [
    ("`x += e`", lambda c: re.sub(r"(?m)^(\s*)(\w+) = \2 ([-+*]) (.+)$", r"\1\2 \3= \4", c)),
    ("in-place `xs.push(e)`", lambda c: re.sub(r"(?m)^(\s*)(\w+) = \2\.(push|set|remove|concat|insert)\(", r"\1\2.\3(", c)),
    ("implicit return of the last line", lambda c: re.sub(r"(?m)^( +)return (.+)\n(?=\}$)", r"\1\2\n", c)),
    ("no `return` at all (upper bound)", lambda c: re.sub(r"\breturn\b ?", "", c)),
    ("inferred types of empty collections", lambda c: re.sub(r"\b(var|let) (\w+): (?:List|Map)\[[^=\n]*\] = ", r"\1 \2 = ", c)),
    ("`get_or` for a match on `get` (exists)", lambda c: GET.sub(lambda m: f"{m[1]}.get_or({m[2]}, {m[4] or m[5]})", c)),
]


def tokens(code):
    return len(TOKEN.findall(code))


def solutions():
    """(run/suite, code of the last answer) of every recorded Klar solution."""
    root = os.path.join(HERE, "results", "agents")
    for path in glob.glob(os.path.join(root, "**", "klar", "*.json"), recursive=True):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not data.get("attempts"):
            continue
        last = data["attempts"][-1]
        code = last.get("code", "") if isinstance(last, dict) else last
        if code:
            yield "/".join(os.path.relpath(path, root).split(os.sep)[:2]), code


def main():
    groups = {}
    for group, code in solutions():
        groups.setdefault(group, []).append(code)
    everything = [code for codes in groups.values() for code in codes]
    with_std = sum(1 for code in everything if re.search(r"(?m)^use std\.", code))
    print(f"{len(everything)} solutions, {with_std} import a std module\n")
    print("| run | tokens | " + " | ".join(name for name, _ in CHANGES) + " |")
    print("|---|---:|" + "---:|" * len(CHANGES))
    for group, codes in sorted(groups.items()):
        total = sum(tokens(code) for code in codes)
        saved = [sum(tokens(code) - tokens(fn(code)) for code in codes) for _, fn in CHANGES]
        print(f"| {group} | {total} | " + " | ".join(f"{100 * s / total:.1f}%" for s in saved) + " |")


if __name__ == "__main__":
    main()
