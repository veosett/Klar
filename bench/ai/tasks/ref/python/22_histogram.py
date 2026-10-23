def histogram(counts: dict[str, int]) -> list[str]:
    return [f"{k}: {'*' * counts[k]}" for k in sorted(counts)]
