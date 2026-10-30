# Pilot: a large change in a large program

Written before any agent saw the task. The question: is Klar better for an AI agent than typed Python when one change
reaches all over a program that is too long to keep in mind? Tokens are one measure among several: the point is the
quality of the result, the speed of the work and how easy the language is for the agent.

## Setup

- **Task:** `b1_shop`, a shop's back office of 35 modules, about 2 950 lines of Klar and 2 830 of Python, built by
  `gen.py`. Three changes in one request (`src/task.md`): money in cents, a new order status, a customer's name split in
  two. The request states rules, not places.
- **Arms:** Klar with its checker (`klar check`), Python with `mypy --strict`. Both programs pass their checker before
  the change. Agents may run their language's checker, tests and program as often as they like.
- **Model and runs:** Haiku, 3 runs per arm, all started together in workspaces with neutral names. At most 3 submissions.
- **Checks:** 45 visible checks answer `submit`; 40 held-out checks never reach the agent and say what would have shipped.
  `main` of the final program must also print what the reference prints.

## Known bias

The two programs are written the way each language is usually written, and this is part of what is measured:
- In Klar most matches over a status list every status, so the checker shows them after the change; a few use `_`. In
  Python most of those places are `in (...)`, `if` chains and dictionaries, which `mypy` does not check.
- Klar has no implicit `Int` to `Float`, so a limit of `50.0` next to cents is an error; for `mypy` it is fine. After only
  the model file changes, `klar check` reports 56 errors in 14 modules and `mypy` 27 in 6 files.
- Against Klar: the agent has never seen it in training and must read a reference; the template modules were written by
  the author of the language; all the code comes from one generator, so it is more regular than real code.

The result therefore compares these two programs. It does not say anything about Python in general.

## Measures

Quality (what the work is for):
- Q1, primary: held-out checks failed by the last submission.
- Q2: `main` of the last submission prints the same as the reference.
- Q3: visible checks failed by the first submission: what the agent missed before any test told it.
- Q4: the task solved within 3 submissions.
- Held-out misses per change (`money`-like, `status:`, `names:`).

Speed:
- S1: wall-clock time of the agent, as the runner reports it.
- S2: tool calls and model turns.
- S3: submissions used.
- S4: seconds of one `klar check` and one `mypy --strict` on the reference, measured alone.

Convenience for the agent:
- C1: total tokens and output tokens.
- C2: how many times the checker was run, and the errors of the language or the tools that the agent hit.
- C3: rule breaks, unfinished runs, places where the agent gave up or the reference misled it (from the transcripts).

## Hypotheses

- H1: Klar fails fewer held-out checks than Python (Q1).
- H2: the gain comes from the money and status changes, not from the names, where `mypy` sees the same places as Klar.
- H3: Klar takes more tokens than Python, as in every earlier run, but the gap is smaller than +55%: the checker replaces
  searching.
- H4: Klar needs no more submissions and no more wall-clock time than Python.

## How to read it

No single score: each measure is reported per run. With 3 runs against 3, an arm wins a measure only if all its runs are
better than all runs of the other arm (the best that 3 against 3 can show, p = 0.1 two-sided), and that is called a
signal, not a proof. Anything else is "no difference seen". If both arms have nothing to miss (Q1 near 0 in all runs), the
task is saturated: the next step is more template modules and harder changes, not a conclusion about the languages.
Results are published whichever way they come out, including against Klar. If Klar shows no gain, its strict rules
need a second look, starting with the ones that cost the most.
