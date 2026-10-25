def multiply_elements(test_tup):
  res = tuple(i * j for i, j in zip(test_tup, test_tup[1:]))
  return (res)


# adapted by bench/ai/build_suites.py: the canonical solution returns tuples where the typed signature says list
# (or lists where it says a pair); the results are converted, the solution itself is unchanged
def _conform(v, t):
    if t.startswith("List["):
        return [_conform(x, t[5:-1]) for x in v]
    if t.startswith("Pair["):
        inner, depth, cut = t[5:-1], 0, 0
        for i, c in enumerate(inner):
            depth += c == "["
            depth -= c == "]"
            if c == "," and depth == 0:
                cut = i
                break
        return (_conform(v[0], inner[:cut].strip()), _conform(v[1], inner[cut + 1:].strip()))
    if t.startswith("Option["):
        return None if v is None else _conform(v, t[7:-1])
    if t.startswith("Map["):
        return {k: _conform(x, t[4:-1].split(",", 1)[1].strip()) for k, x in v.items()}
    return v


_canonical_multiply_elements = multiply_elements


def multiply_elements(*args):
    return _conform(_canonical_multiply_elements(*args), 'List[Int]')
