def run_ops(ops: list[str]) -> int:
    balance = 0
    for i, op in enumerate(ops, 1):
        parts = op.split(" ")
        if len(parts) != 2 or parts[0] not in ("deposit", "withdraw") or not parts[1].isdigit():
            raise ValueError(f"bad op at op {i}")
        n = int(parts[1])
        if parts[0] == "deposit":
            balance += n
        elif balance - n < 0:
            raise ValueError(f"insufficient funds at op {i}")
        else:
            balance -= n
    return balance
