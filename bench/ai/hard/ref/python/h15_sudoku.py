def sudoku(rows: list[str]) -> bool:
    if len(rows) != 9 or any(len(r) != 9 for r in rows):
        return False
    seen = set()
    for r, row in enumerate(rows):
        for c, ch in enumerate(row):
            if ch == ".":
                continue
            if ch not in "123456789":
                return False
            for unit in (("r", r), ("c", c), ("b", r // 3, c // 3)):
                if (unit, ch) in seen:
                    return False
                seen.add((unit, ch))
    return True
