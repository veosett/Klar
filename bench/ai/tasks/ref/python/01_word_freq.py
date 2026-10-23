def word_freq(text: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for w in text.split():
        w = w.lower()
        out[w] = out.get(w, 0) + 1
    return out
