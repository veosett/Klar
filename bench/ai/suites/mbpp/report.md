# mbpp: 334 of 400 problems

Built by `bench/ai/build_suites.py` from MultiPL-E at commit `3025a531af7450e7df8b96fe0440e9804480bbad`.

Kept: 334 problems, 1037 test cases (each passed by the canonical Python solution, called with the typed arguments). In 10 references the results are converted to the declared type (tuples where the signature says list); the solutions themselves are unchanged.

| skipped problems: reason | count |
|---|---:|
| type Any | 19 |
| type Union | 13 |
| a tuple of 3 | 13 |
| a tuple of 4 | 6 |
| the canonical solution fails some of its typed tests | 4 |
| a map with non-string keys | 3 |
| a tuple of 5 | 3 |
| type Set | 2 |
| returns None | 1 |
| annotation Constant(value=Ellipsis) | 1 |
| a tuple of 6 | 1 |

| dropped test cases of kept problems: reason | count |
|---|---:|
| not an Int, or one above 2^53 (TypeScript cannot hold it exactly) | 1 |
