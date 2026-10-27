import { Txn, amount_of, is_credit } from "./txn";

/** One transaction as text. */
export function describe(t: Txn): string {
  switch (t.kind) {
    case "Deposit":
      return `deposit of ${t.amount}`;
    case "Withdraw":
      return `withdrawal of ${t.amount}`;
    case "Transfer":
      return `transfer of ${t.amount} to ${t.to}`;
    case "Refund":
      return `refund of ${t.amount} for order ${t.order}`;
  }
}

/** Counts per kind and the money that came in and went out. */
export interface Summary {
  deposits: number;
  withdrawals: number;
  transfers: number;
  refunds: number;
  money_in: number;
  money_out: number;
}

function tally(s: Summary, t: Txn): Summary {
  switch (t.kind) {
    case "Deposit":
      return { ...s, deposits: s.deposits + 1, money_in: s.money_in + t.amount };
    case "Withdraw":
      return { ...s, withdrawals: s.withdrawals + 1, money_out: s.money_out + t.amount };
    case "Transfer":
      return { ...s, transfers: s.transfers + 1, money_out: s.money_out + t.amount };
    case "Refund":
      return { ...s, refunds: s.refunds + 1, money_in: s.money_in + t.amount };
  }
}

export function summarize(txns: Txn[]): Summary {
  const empty: Summary = { deposits: 0, withdrawals: 0, transfers: 0, refunds: 0, money_in: 0, money_out: 0 };
  return txns.reduce(tally, empty);
}

/** The summary as lines of text. */
export function summary_text(s: Summary): string {
  const lines = [
    `deposits: ${s.deposits}`,
    `withdrawals: ${s.withdrawals}`,
    `transfers: ${s.transfers}`,
    `refunds: ${s.refunds}`,
    `in: ${s.money_in}`,
    `out: ${s.money_out}`,
  ];
  return lines.join("\n");
}

function kind_order(t: Txn): number {
  switch (t.kind) {
    case "Deposit":
      return 0;
    case "Withdraw":
      return 1;
    case "Transfer":
      return 2;
    case "Refund":
      return 3;
  }
}

/** The transactions grouped by kind (deposits, withdrawals, transfers, refunds), the original order kept inside a kind. */
export function sorted_by_kind(txns: Txn[]): Txn[] {
  return [...txns].sort((a, b) => kind_order(a) - kind_order(b));
}

/** The largest transaction, if any. */
export function largest(txns: Txn[]): Txn | undefined {
  let best: Txn | undefined = undefined;
  for (const t of txns) {
    if (best === undefined || amount_of(t) > amount_of(best)) {
      best = t;
    }
  }
  return best;
}

/** Money in minus money out over all transactions. */
export function net_change(txns: Txn[]): number {
  return txns.reduce((sum, t) => (is_credit(t) ? sum + amount_of(t) : sum - amount_of(t)), 0);
}

/** One line per transaction, numbered from 1. */
export function describe_all(txns: Txn[]): string[] {
  return txns.map((t, i) => `${i + 1}. ${describe(t)}`);
}
