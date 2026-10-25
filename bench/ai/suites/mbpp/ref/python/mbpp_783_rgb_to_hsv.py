def rgb_to_hsv(r, g, b):
    r, g, b = r/255.0, g/255.0, b/255.0
    mx = max(r, g, b)
    mn = min(r, g, b)
    df = mx-mn
    if mx == mn:
        h = 0
    elif mx == r:
        h = (60 * ((g-b)/df) + 360) % 360
    elif mx == g:
        h = (60 * ((b-r)/df) + 120) % 360
    elif mx == b:
        h = (60 * ((r-g)/df) + 240) % 360
    if mx == 0:
        s = 0
    else:
        s = (df/mx)*100
    v = mx*100
    return h, s, v


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


_canonical_rgb_to_hsv = rgb_to_hsv


def rgb_to_hsv(*args):
    return _conform(_canonical_rgb_to_hsv(*args), 'List[Float]')
