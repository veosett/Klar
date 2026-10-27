import { Txn, validate } from "./txn";

function take(balance: number, amount: number): number {
  if (amount > balance) {
    throw new Error(`insufficient funds: balance ${balance}, need ${amount}`);
  }
  return balance - amount;
}

/** The balance after one transaction. Throws when a withdrawal or a transfer exceeds the balance. */
export function apply(balance: number, t: Txn): number {
  switch (t.kind) {
    case "Deposit":
      return balance + t.amount;
    case "Withdraw":
      return take(balance, t.amount);
    case "Transfer":
      return take(balance, t.amount);
    case "Refund":
      return balance + t.amount;
  }
}

/** Validates and applies the transactions in order; errors say which one (1-based) failed. */
export function apply_all(balance: number, txns: Txn[]): number {
  let current = balance;
  txns.forEach((t, i) => {
    try {
      validate(t);
      current = apply(current, t);
    } catch (e) {
      throw new Error(`txn ${i + 1}: ${(e as Error).message}`);
    }
  });
  return current;
}

/** The balance after each transaction (the start balance is not included). */
export function history(balance: number, txns: Txn[]): number[] {
  let current = balance;
  const seen: number[] = [];
  for (const t of txns) {
    current = apply(current, t);
    seen.push(current);
  }
  return seen;
}
