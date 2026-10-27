import sys
from typing import Any, Callable

from txn import Deposit, Withdraw, Transfer, Refund, Txn, amount_of, validate, is_credit
from ledger import apply, apply_all, history
from fees import fee_for, total_fees
from report import describe, summarize, summary_text, sorted_by_kind, largest, net_change, describe_all

failed = 0


def check(what: str, run: Callable[[], Any], expected: Any) -> None:
    global failed
    try:
        got = run()
    except Exception as e:  # a crash is a failed check, not the end of the run
        got = f"raised {type(e).__name__}: {e}"
    if got != expected:
        failed += 1
        print(f"FAIL: {what}, got {got!r}, expected {expected!r}")


def verdict(t: Txn) -> str:
    try:
        validate(t)
        return "ok"
    except ValueError as e:
        return str(e)


def result(f: Callable[..., Any], *args: Any) -> tuple[str, Any]:
    try:
        return ("ok", f(*args))
    except ValueError as e:
        return ("err", str(e))


def refund(order: str, amount: int) -> Txn:
    return Refund(order, amount)


def dep(amount: int) -> Txn:
    return Deposit(amount)


def wd(amount: int) -> Txn:
    return Withdraw(amount)


def tr(to: str, amount: int) -> Txn:
    return Transfer(to, amount)


# txn: amount_of and is_credit
check("amount_of refund", lambda: amount_of(refund("A-17", 30)), 30)
check("is_credit refund", lambda: is_credit(refund("A-17", 30)), True)
check("is_credit deposit", lambda: is_credit(dep(1)), True)
check("is_credit withdraw", lambda: is_credit(wd(1)), False)
check("is_credit transfer", lambda: is_credit(tr("bob", 1)), False)

# txn: validate refunds
check("validate valid refund", lambda: verdict(refund("A-17", 30)), "ok")
check("validate refund with empty order", lambda: verdict(refund("", 30)), "refund needs an order id")
check("validate refund with amount 0", lambda: verdict(refund("A-1", 0)), "amount must be positive")
check("validate refund with negative amount", lambda: verdict(refund("A-1", -5)), "amount must be positive")
check("validate refund with empty order and amount 0", lambda: verdict(refund("", 0)), "refund needs an order id")

# txn: validate other kinds still works
check("validate deposit 0", lambda: verdict(dep(0)), "amount must be positive")
check("validate transfer without destination", lambda: verdict(tr("", 5)), "transfer needs a destination")
check("validate valid transfer", lambda: verdict(tr("bob", 5)), "ok")

# ledger: apply
check("apply refund", lambda: result(apply, 50, refund("A-17", 30)), ("ok", 80))
check("apply refund to empty balance", lambda: result(apply, 0, refund("X", 7)), ("ok", 7))
check("apply withdraw over balance", lambda: result(apply, 10, wd(40)), ("err", "insufficient funds: balance 10, need 40"))
check("apply transfer over balance", lambda: result(apply, 10, tr("bob", 11)), ("err", "insufficient funds: balance 10, need 11"))
check("apply deposit", lambda: result(apply, 10, dep(5)), ("ok", 15))

# ledger: apply_all and history
check("apply_all with a refund", lambda: result(apply_all, 100, [dep(100), refund("A-17", 30), wd(40)]), ("ok", 190))
check("apply_all invalid refund order", lambda: result(apply_all, 0, [refund("", 5)]), ("err", "txn 1: refund needs an order id"))
check("apply_all overdraft after refund", lambda: result(apply_all, 10, [refund("A-17", 30), wd(100)]),
      ("err", "txn 2: insufficient funds: balance 40, need 100"))
check("apply_all invalid refund amount", lambda: result(apply_all, 0, [dep(1), refund("A", 0)]),
      ("err", "txn 2: amount must be positive"))
check("history with refunds", lambda: result(history, 10, [refund("A-17", 30), wd(40), refund("B", 5)]), ("ok", [40, 0, 5]))

# fees: fee_for
check("fee_for refund", lambda: fee_for(refund("A-17", 30)), 0)
check("fee_for big refund", lambda: fee_for(refund("B", 5000)), 0)
check("fee_for deposit", lambda: fee_for(dep(10)), 0)
check("fee_for withdraw", lambda: fee_for(wd(10)), 2)
check("fee_for transfer 2500", lambda: fee_for(tr("bob", 2500)), 7)

# fees: total_fees
check("total_fees mixed", lambda: total_fees([dep(100), wd(40), tr("bob", 25), refund("A-17", 30)]), 7)
check("total_fees refunds only", lambda: total_fees([refund("A-17", 30), refund("B", 5000)]), 0)

# report: describe
check("describe refund", lambda: describe(refund("A-17", 30)), "refund of 30 for order A-17")
check("describe transfer", lambda: describe(tr("bob", 25)), "transfer of 25 to bob")
check("describe withdraw", lambda: describe(wd(40)), "withdrawal of 40")
check("describe deposit", lambda: describe(dep(100)), "deposit of 100")

# report: summarize counts
mixed = [dep(100), refund("A-17", 30), wd(40), tr("bob", 25), refund("B-2", 20)]
check("summarize deposits", lambda: summarize(mixed).deposits, 1)
check("summarize withdrawals", lambda: summarize(mixed).withdrawals, 1)
check("summarize transfers", lambda: summarize(mixed).transfers, 1)
check("summarize refunds", lambda: summarize(mixed).refunds, 2)
check("summarize money_in", lambda: summarize(mixed).money_in, 150)
check("summarize money_out", lambda: summarize(mixed).money_out, 65)

# report: summarize without refunds
plain = [dep(10), dep(5), wd(3)]
check("summarize plain refunds", lambda: summarize(plain).refunds, 0)
check("summarize plain money_in", lambda: summarize(plain).money_in, 15)
check("summarize plain money_out", lambda: summarize(plain).money_out, 3)
check("summarize empty refunds", lambda: summarize([]).refunds, 0)

# report: summary_text
check("summary_text mixed", lambda: summary_text(summarize(mixed)),
      "deposits: 1\nwithdrawals: 1\ntransfers: 1\nrefunds: 2\nin: 150\nout: 65")
check("summary_text empty", lambda: summary_text(summarize([])),
      "deposits: 0\nwithdrawals: 0\ntransfers: 0\nrefunds: 0\nin: 0\nout: 0")

# report: sorted_by_kind puts refunds last
check("sorted_by_kind", lambda: describe_all(sorted_by_kind(
    [refund("A-17", 30), tr("bob", 25), refund("Z", 1), wd(40), dep(100), dep(5)])),
    ["1. deposit of 100", "2. deposit of 5", "3. withdrawal of 40", "4. transfer of 25 to bob",
     "5. refund of 30 for order A-17", "6. refund of 1 for order Z"])

# report: net_change, largest
check("net_change mixed", lambda: net_change([dep(100), refund("A-17", 30), wd(40), tr("bob", 25)]), 65)
check("net_change refund only", lambda: net_change([refund("A-17", 30)]), 30)
check("largest with refunds", lambda: describe(largest([dep(100), refund("A-17", 30), refund("Big", 500), wd(40)])),  # type: ignore[arg-type]
      "refund of 500 for order Big")
check("largest of nothing", lambda: largest([]), None)

sys.exit(1 if failed else 0)
