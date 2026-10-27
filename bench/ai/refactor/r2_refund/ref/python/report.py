from dataclasses import dataclass

from txn import Txn, Deposit, Withdraw, Transfer, Refund, amount_of, is_credit


def describe(t: Txn) -> str:
    """One transaction as text."""
    match t:
        case Deposit(a):
            return f"deposit of {a}"
        case Withdraw(a):
            return f"withdrawal of {a}"
        case Transfer(to, a):
            return f"transfer of {a} to {to}"
        case Refund(order, a):
            return f"refund of {a} for order {order}"


@dataclass(frozen=True)
class Summary:
    """Counts per kind and the money that came in and went out."""
    deposits: int
    withdrawals: int
    transfers: int
    refunds: int
    money_in: int
    money_out: int


def _tally(s: Summary, t: Txn) -> Summary:
    match t:
        case Deposit(a):
            return Summary(s.deposits + 1, s.withdrawals, s.transfers, s.refunds, s.money_in + a, s.money_out)
        case Withdraw(a):
            return Summary(s.deposits, s.withdrawals + 1, s.transfers, s.refunds, s.money_in, s.money_out + a)
        case Transfer(_, a):
            return Summary(s.deposits, s.withdrawals, s.transfers + 1, s.refunds, s.money_in, s.money_out + a)
        case Refund(_, a):
            return Summary(s.deposits, s.withdrawals, s.transfers, s.refunds + 1, s.money_in + a, s.money_out)


def summarize(txns: list[Txn]) -> Summary:
    s = Summary(0, 0, 0, 0, 0, 0)
    for t in txns:
        s = _tally(s, t)
    return s


def summary_text(s: Summary) -> str:
    """The summary as lines of text."""
    lines = [
        f"deposits: {s.deposits}",
        f"withdrawals: {s.withdrawals}",
        f"transfers: {s.transfers}",
        f"refunds: {s.refunds}",
        f"in: {s.money_in}",
        f"out: {s.money_out}",
    ]
    return "\n".join(lines)


def _kind_order(t: Txn) -> int:
    match t:
        case Deposit(_):
            return 0
        case Withdraw(_):
            return 1
        case Transfer(_, _):
            return 2
        case Refund(_, _):
            return 3


def sorted_by_kind(txns: list[Txn]) -> list[Txn]:
    """The transactions grouped by kind (deposits, withdrawals, transfers, refunds), the original order kept inside a kind."""
    return sorted(txns, key=_kind_order)


def largest(txns: list[Txn]) -> Txn | None:
    """The largest transaction, if any."""
    if not txns:
        return None
    return max(txns, key=amount_of)


def net_change(txns: list[Txn]) -> int:
    """Money in minus money out over all transactions."""
    return sum(amount_of(t) if is_credit(t) else -amount_of(t) for t in txns)


def describe_all(txns: list[Txn]) -> list[str]:
    """One line per transaction, numbered from 1."""
    return [f"{i}. {describe(t)}" for i, t in enumerate(txns, start=1)]
