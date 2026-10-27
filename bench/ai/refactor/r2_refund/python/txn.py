from dataclasses import dataclass


@dataclass(frozen=True)
class Deposit:
    amount: int


@dataclass(frozen=True)
class Withdraw:
    amount: int


@dataclass(frozen=True)
class Transfer:
    to: str
    amount: int


# A bank transaction. Amounts are whole currency units.
Txn = Deposit | Withdraw | Transfer


def amount_of(t: Txn) -> int:
    """The amount of money a transaction moves."""
    match t:
        case Deposit(a):
            return a
        case Withdraw(a):
            return a
        case Transfer(_, a):
            return a


def validate(t: Txn) -> None:
    """Checks a transaction; raises ValueError saying what is wrong."""
    match t:
        case Transfer(to, _):
            if to == "":
                raise ValueError("transfer needs a destination")
        case _:
            pass
    if amount_of(t) <= 0:
        raise ValueError("amount must be positive")


def is_credit(t: Txn) -> bool:
    """True when the transaction adds money to the balance."""
    match t:
        case Deposit(_):
            return True
        case Withdraw(_):
            return False
        case Transfer(_, _):
            return False
