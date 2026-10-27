import { Txn } from "./txn";

/** The fee charged for one transaction. */
export function fee_for(t: Txn): number {
  switch (t.kind) {
    case "Deposit":
      return 0;
    case "Withdraw":
      return 2;
    case "Transfer":
      return 5 + Math.floor(t.amount / 1000);
  }
}

/** The sum of the fees of all transactions. */
export function total_fees(txns: Txn[]): number {
  return txns.reduce((sum, t) => sum + fee_for(t), 0);
}
