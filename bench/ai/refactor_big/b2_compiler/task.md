Add a pipe operator `|>` to the Klar language, in this implementation of Klar. Nobody has a list of the places to change:
find them yourself. Everything that works now must keep working.

## Syntax

`value |> f(args)`. The right side is a call of a function by its plain name, as in `f(args)`; generic functions and named
arguments work as in any call.

- It is left associative: `a |> f() |> g()` is `(a |> f()) |> g()`.
- It binds looser than every other operator, `or` included: `1 + 2 |> f()` is `(1 + 2) |> f()`, and `a or b |> f()` is
  `(a or b) |> f()`. Use parentheses for anything else: `(a |> f()) + 1`, `(a |> f())?`.
- A line that starts with `|>` continues the expression of the line before, as a line that starts with `.` does.
- `|>` works wherever an expression does, string interpolation included.

## Meaning

`a |> f(b)` means `f(a, b)`: `a` becomes the first argument, and it is evaluated before the others. A named argument
names one of the remaining parameters: `a |> f(b: 1)`.

The compiler treats it exactly as that call, so it reports the same error or warning codes for the same mistakes (wrong
type, wrong number of arguments, unknown function, missing effects, a discarded `Result`, an unused value, a broken
`requires`, a division that may be by zero, and so on), and a variable or a function that is used only in a pipe counts
as used.

## A new error

If the right side is anything other than such a call (`3 |> 4`, `3 |> x.f()`, `3 |> f`), the error is
`E0225` with the message ``the right side of `|>` must be a call``. `klar explain E0225` explains it.

## The syntax tree

The parser does not rewrite a pipe into a call: it is a node of its own. `klar ast` shows it as
`{"node": "Pipe", ..., "value": <the left side>, "call": <the Call node as written, without the value>}`, with `id` and
`span` as any other node has.

## The tools

Every command handles a pipe, and treats it as the call it means:

- `klar run`, `klar test` (doc-tests too), `klar eval`, and the rest of what runs programs.
- `klar fmt` writes `a |> f(b)` on one line with one space around `|>`, and keeps the parentheses that the meaning needs.
- `klar refs` and `klar rename` find and change the names on both sides of a pipe.
- `klar context` lists a function with a pipe to `f` among the callers of `f`.
- `klar coverage` counts what runs through a pipe.

The rest of the tools follow the same principle.
