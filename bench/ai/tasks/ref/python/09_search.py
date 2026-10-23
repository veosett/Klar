def find_index(sorted: list[int], target: int) -> int | None:
    lo, hi = 0, len(sorted) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if sorted[mid] == target:
            return mid
        if sorted[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return None
