export interface Deposit {
  kind: "Deposit";
  amount: number;
}

export interface Withdraw {
  kind: "Withdraw";
  amount: number;
}

export interface Transfer {
  kind: "Transfer";
  to: string;
  amount: number;
}

// A bank transaction. Amounts are whole currency units.
export type Txn = Deposit | Withdraw | Transfer;

/** The amount of money a transaction moves. */
export function amount_of(t: Txn): number {
  switch (t.kind) {
    case "Deposit":
      return t.amount;
    case "Withdraw":
      return t.amount;
    case "Transfer":
      return t.amount;
  }
}

/** Checks a transaction; throws an Error saying what is wrong. */
export function validate(t: Txn): void {
  if (t.kind === "Transfer" && t.to === "") {
    throw new Error("transfer needs a destination");
  }
  if (amount_of(t) <= 0) {
    throw new Error("amount must be positive");
  }
}

/** True when the transaction adds money to the balance. */
export function is_credit(t: Txn): boolean {
  switch (t.kind) {
    case "Deposit":
      return true;
    case "Withdraw":
      return false;
    case "Transfer":
      return false;
  }
}
