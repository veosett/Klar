# A change in the real compiler

Written before any measured agent saw the task. The first pilot (`b1_shop`) hit the ceiling: its code was uniform and the
part that mattered fit in one reading. Here the program is the implementation of Klar itself, written in Klar and in
Python, with the same behaviour and the same command line, and it does not fit in one reading.

## Setup

- **Task:** add a pipe operator `|>` (`task.md`): syntax, meaning, a new error, a node of its own in the tree, every tool.
  The request states rules, not places.
- **Arms:** `compiler/` in Klar (36 100 lines without the generated library, checked by `klar check`, built in about 35 s)
  and `klar/` in Python (18 600 lines, no build; `mypy` is available).
- **Model and runs:** Haiku, 3 runs per arm, started together in workspaces with neutral names. At most 3 submissions.
- **Checks** (`checks.py`): 17 visible checks answer `submit`; 27 held-out checks never reach the agent. Each runs a
  command of the implementation on a small program. Both references pass all 44 (`ref/`, written by Sonnet from the
  request alone, before they saw whether their checks were right; three wrong checks were corrected then).

## Known bias

- **For Klar:** the checks were written knowing that tools walk the tree, which is where exhaustive matches help.
  The checks are the author's choice.
- **For Python:** it is half as long, needs no build, and a 35 s build slows every Klar loop. Its dynamic style lets a
  single rewrite after type checking serve every engine: the reference touches 8 files (150 lines changed) against 14 files
  (191 lines) in Klar. That is a real advantage of the language, not noise.
- **Against Python:** `mypy` barely helps here, since this code is not typed for it (49 errors without `--strict`, 8 307 with
  it). So this compares Klar's checker with loosely typed Python, as real code often is, and not with fully typed Python.
- **Against Klar:** Haiku has never seen it in training, and the agent must also read Klar to change it, not only to test it.
- Both agents have to write Klar programs to test their work; both get the reference.

## Measures

Quality:
- Q1, primary: held-out checks failed by the last submission.
- Q2: visible checks failed by the first submission.
- Q3: visible checks failed by the last submission; solved within 3 submissions.
- Which held-out checks failed, by group (`run`, `check`, `test`/`eval`, `ast`, `fmt`, tools).

Speed:
- S1: wall-clock time of the agent. S2: model turns and tool calls. S3: submissions used.
- S4: the time of a check and of a build, measured alone.

Convenience and cost:
- C1: total and output tokens.
- C2: how many times the checker ran, how many errors the agent hit, which tools it used.
- C3: rule breaks, unfinished runs, places where the agent gave up (from the transcripts).

## Hypotheses

- H1: Klar fails fewer held-out checks than Python (Q1).
- H2: Python's misses are mostly in the tools and the checker, Klar's in behaviour that no match can show (`fmt`, `explain`).
- H3: Klar costs more time and tokens than Python (twice the code, a build in every loop).
- H4: Klar reaches a passing `submit` in no more submissions than Python.

## How to read it

As in the pilot: each measure per run, a signal only when all 3 runs of one arm are better than all 3 of the other, and
no single score. If the arms fail few held-out checks (at most 2 of 27 on average in both), the task is saturated again
and says nothing about H1. If quality is better in Klar and it costs more, that is the trade to report as it is, with both
numbers; which way the trade goes is a decision, not a measurement.
