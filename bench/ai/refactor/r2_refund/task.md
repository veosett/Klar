The bank ledger (modules `txn`, `ledger`, `fees`, `report`) gets a fourth kind of transaction, `Refund`, with two fields:
`order` (Str, a non-empty order id) and `amount` (Int, must be > 0). Klar: `Txn.Refund(order: Str, amount: Int)`.
Python: a frozen dataclass `Refund(order, amount)` that is part of the `Txn` union. TypeScript: an exported interface
`Refund { kind: "Refund"; order: string; amount: number }` that is part of the `Txn` union.

Rules (every one must hold; the texts are exact):
- `txn.amount_of(t)` returns the amount of a refund.
- `txn.validate(t)` rejects a refund with an empty `order` with the error "refund needs an order id", and a refund whose
  amount is <= 0 with the same error as for the other kinds ("amount must be positive"). The order is checked first:
  a refund with an empty order and amount 0 gives "refund needs an order id". Valid refunds are accepted.
- `txn.is_credit(t)` is true for a refund (it adds money to the balance).
- `ledger.apply(balance, t)` for a refund returns `balance + amount` (it never fails); `apply_all` and `history` therefore
  handle refunds too, and `apply_all` reports an invalid refund as "txn N: <validate message>".
- `fees.fee_for(t)` is 0 for a refund, so refunds add nothing to `fees.total_fees`.
- `report.describe(t)` for a refund is exactly "refund of N for order X", e.g. "refund of 30 for order A-17".
- `report.Summary` gets a new Int field `refunds` (the number of refunds). `report.summarize` counts refunds there and
  adds their amounts to `money_in`; they never count in `deposits`, `withdrawals`, `transfers` or `money_out`.
- `report.summary_text(s)` gets a new line "refunds: N" between the "transfers: N" and the "in: N" lines; the other
  lines keep their text, so the lines are: deposits, withdrawals, transfers, refunds, in, out.
- `report.sorted_by_kind` puts refunds last: deposits, withdrawals, transfers, then refunds (the original order is kept
  inside a kind).
- `report.net_change` and `report.describe_all` must work with refunds (a refund counts as money in).

Everything that already works for the other kinds keeps its behaviour.
