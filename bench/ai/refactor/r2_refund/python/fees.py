from txn import Txn, Deposit, Withdraw, Transfer


def fee_for(t: Txn) -> int:
    """The fee charged for one transaction."""
    match t:
        case Deposit(_):
            return 0
        case Withdraw(_):
            return 2
        case Transfer(_, a):
            return 5 + a // 1000


def total_fees(txns: list[Txn]) -> int:
    """The sum of the fees of all transactions."""
    return sum(fee_for(t) for t in txns)
