# humaneval_plus: 154 of 161 problems

Built by `bench/ai/build_suites.py` from MultiPL-E at commit `3025a531af7450e7df8b96fe0440e9804480bbad`.

Kept: 154 problems, 8316 test cases (each passed by the canonical Python solution, called with the typed arguments). In 0 references the results are converted to the declared type (tuples where the signature says list); the solutions themselves are unchanged.

| skipped problems: reason | count |
|---|---:|
| type Union | 3 |
| the canonical solution fails some of its typed tests | 2 |
| type Any | 1 |
| annotation Constant(value=Ellipsis) | 1 |

| dropped test cases of kept problems: reason | count |
|---|---:|
| extra input: not an Int, or one above 2^53 (TypeScript cannot hold it exactly) | 509 |
| extra input: larger than 2000 characters as a test | 66 |
| extra input: a value that is not a List | 57 |
| extra input: a value that is not a Str | 29 |
| Float result: no extra inputs | 7 |
| not an Int, or one above 2^53 (TypeScript cannot hold it exactly) | 1 |
