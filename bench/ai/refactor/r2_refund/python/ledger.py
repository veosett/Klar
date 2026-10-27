from txn import Txn, Deposit, Withdraw, Transfer, validate


def _take(balance: int, amount: int) -> int:
    if amount > balance:
        raise ValueError(f"insufficient funds: balance {balance}, need {amount}")
    return balance - amount


def apply(balance: int, t: Txn) -> int:
    """The balance after one transaction. Raises ValueError when a withdrawal or a transfer exceeds the balance."""
    match t:
        case Deposit(a):
            return balance + a
        case Withdraw(a):
            return _take(balance, a)
        case Transfer(_, a):
            return _take(balance, a)


def apply_all(balance: int, txns: list[Txn]) -> int:
    """Validates and applies the transactions in order; errors say which one (1-based) failed."""
    current = balance
    for i, t in enumerate(txns, start=1):
        try:
            validate(t)
            current = apply(current, t)
        except ValueError as e:
            raise ValueError(f"txn {i}: {e}") from None
    return current


def history(balance: int, txns: list[Txn]) -> list[int]:
    """The balance after each transaction (the start balance is not included)."""
    current = balance
    seen: list[int] = []
    for t in txns:
        current = apply(current, t)
        seen.append(current)
    return seen
