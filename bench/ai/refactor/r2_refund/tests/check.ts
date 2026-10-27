import { Txn, amount_of, validate, is_credit } from "./txn";
import { apply, apply_all, history } from "./ledger";
import { fee_for, total_fees } from "./fees";
import { describe, summarize, summary_text, sorted_by_kind, largest, net_change, describe_all } from "./report";

declare const process: { exit(code: number): never };

let failed = 0;

function check(what: string, run: () => unknown, expected: unknown): void {
  let got: unknown;
  try {
    got = run();
  } catch (e) {
    got = `raised ${(e as Error).message}`;
  }
  if (JSON.stringify(got) !== JSON.stringify(expected)) {
    failed += 1;
    console.log(`FAIL: ${what}, got ${JSON.stringify(got)}, expected ${JSON.stringify(expected)}`);
  }
}

function verdict(t: Txn): string {
  try {
    validate(t);
    return "ok";
  } catch (e) {
    return (e as Error).message;
  }
}

function result<A extends unknown[]>(f: (...args: A) => unknown, ...args: A): [string, unknown] {
  try {
    return ["ok", f(...args)];
  } catch (e) {
    return ["err", (e as Error).message];
  }
}

function refund(order: string, amount: number): Txn {
  return { kind: "Refund", order, amount };
}

function dep(amount: number): Txn {
  return { kind: "Deposit", amount };
}

function wd(amount: number): Txn {
  return { kind: "Withdraw", amount };
}

function tr(to: string, amount: number): Txn {
  return { kind: "Transfer", to, amount };
}

// txn: amount_of and is_credit
check("amount_of refund", () => amount_of(refund("A-17", 30)), 30);
check("is_credit refund", () => is_credit(refund("A-17", 30)), true);
check("is_credit deposit", () => is_credit(dep(1)), true);
check("is_credit withdraw", () => is_credit(wd(1)), false);
check("is_credit transfer", () => is_credit(tr("bob", 1)), false);

// txn: validate refunds
check("validate valid refund", () => verdict(refund("A-17", 30)), "ok");
check("validate refund with empty order", () => verdict(refund("", 30)), "refund needs an order id");
check("validate refund with amount 0", () => verdict(refund("A-1", 0)), "amount must be positive");
check("validate refund with negative amount", () => verdict(refund("A-1", -5)), "amount must be positive");
check("validate refund with empty order and amount 0", () => verdict(refund("", 0)), "refund needs an order id");

// txn: validate other kinds still works
check("validate deposit 0", () => verdict(dep(0)), "amount must be positive");
check("validate transfer without destination", () => verdict(tr("", 5)), "transfer needs a destination");
check("validate valid transfer", () => verdict(tr("bob", 5)), "ok");

// ledger: apply
check("apply refund", () => result(apply, 50, refund("A-17", 30)), ["ok", 80]);
check("apply refund to empty balance", () => result(apply, 0, refund("X", 7)), ["ok", 7]);
check("apply withdraw over balance", () => result(apply, 10, wd(40)), ["err", "insufficient funds: balance 10, need 40"]);
check("apply transfer over balance", () => result(apply, 10, tr("bob", 11)), ["err", "insufficient funds: balance 10, need 11"]);
check("apply deposit", () => result(apply, 10, dep(5)), ["ok", 15]);

// ledger: apply_all and history
check("apply_all with a refund", () => result(apply_all, 100, [dep(100), refund("A-17", 30), wd(40)]), ["ok", 190]);
check("apply_all invalid refund order", () => result(apply_all, 0, [refund("", 5)]), ["err", "txn 1: refund needs an order id"]);
check("apply_all overdraft after refund", () => result(apply_all, 10, [refund("A-17", 30), wd(100)]),
  ["err", "txn 2: insufficient funds: balance 40, need 100"]);
check("apply_all invalid refund amount", () => result(apply_all, 0, [dep(1), refund("A", 0)]),
  ["err", "txn 2: amount must be positive"]);
check("history with refunds", () => result(history, 10, [refund("A-17", 30), wd(40), refund("B", 5)]), ["ok", [40, 0, 5]]);

// fees: fee_for
check("fee_for refund", () => fee_for(refund("A-17", 30)), 0);
check("fee_for big refund", () => fee_for(refund("B", 5000)), 0);
check("fee_for deposit", () => fee_for(dep(10)), 0);
check("fee_for withdraw", () => fee_for(wd(10)), 2);
check("fee_for transfer 2500", () => fee_for(tr("bob", 2500)), 7);

// fees: total_fees
check("total_fees mixed", () => total_fees([dep(100), wd(40), tr("bob", 25), refund("A-17", 30)]), 7);
check("total_fees refunds only", () => total_fees([refund("A-17", 30), refund("B", 5000)]), 0);

// report: describe
check("describe refund", () => describe(refund("A-17", 30)), "refund of 30 for order A-17");
check("describe transfer", () => describe(tr("bob", 25)), "transfer of 25 to bob");
check("describe withdraw", () => describe(wd(40)), "withdrawal of 40");
check("describe deposit", () => describe(dep(100)), "deposit of 100");

// report: summarize counts
const mixed = [dep(100), refund("A-17", 30), wd(40), tr("bob", 25), refund("B-2", 20)];
check("summarize deposits", () => summarize(mixed).deposits, 1);
check("summarize withdrawals", () => summarize(mixed).withdrawals, 1);
check("summarize transfers", () => summarize(mixed).transfers, 1);
check("summarize refunds", () => summarize(mixed).refunds, 2);
check("summarize money_in", () => summarize(mixed).money_in, 150);
check("summarize money_out", () => summarize(mixed).money_out, 65);

// report: summarize without refunds
const plain = [dep(10), dep(5), wd(3)];
check("summarize plain refunds", () => summarize(plain).refunds, 0);
check("summarize plain money_in", () => summarize(plain).money_in, 15);
check("summarize plain money_out", () => summarize(plain).money_out, 3);
check("summarize empty refunds", () => summarize([]).refunds, 0);

// report: summary_text
check("summary_text mixed", () => summary_text(summarize(mixed)),
  "deposits: 1\nwithdrawals: 1\ntransfers: 1\nrefunds: 2\nin: 150\nout: 65");
check("summary_text empty", () => summary_text(summarize([])),
  "deposits: 0\nwithdrawals: 0\ntransfers: 0\nrefunds: 0\nin: 0\nout: 0");

// report: sorted_by_kind puts refunds last
check("sorted_by_kind", () => describe_all(sorted_by_kind(
  [refund("A-17", 30), tr("bob", 25), refund("Z", 1), wd(40), dep(100), dep(5)])),
  ["1. deposit of 100", "2. deposit of 5", "3. withdrawal of 40", "4. transfer of 25 to bob",
   "5. refund of 30 for order A-17", "6. refund of 1 for order Z"]);

// report: net_change, largest
check("net_change mixed", () => net_change([dep(100), refund("A-17", 30), wd(40), tr("bob", 25)]), 65);
check("net_change refund only", () => net_change([refund("A-17", 30)]), 30);
check("largest with refunds", () => {
  const t = largest([dep(100), refund("A-17", 30), refund("Big", 500), wd(40)]);
  return t === undefined ? "none" : describe(t);
}, "refund of 500 for order Big");
check("largest of nothing", () => largest([]) === undefined, true);

process.exit(failed > 0 ? 1 : 0);
