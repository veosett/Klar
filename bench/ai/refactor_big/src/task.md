The shop's back office (start from `main`) needs three changes. They reach all over the program, and nobody has a list
of the places: find them yourself. Keep the names of modules and functions, and the arguments of functions in their
order, unless a change says otherwise. Where a rule below does not change something, it keeps working as it does now.

## 1. Money in whole cents

Floating point money causes rounding errors, so the sales side moves to whole cents: `Product.price`, `Line.unit_price`,
`Order.shipping` and every amount of money that the sales modules take or return become integers in cents. 12.50 is now
`1250`. Rules:

- Every amount written in the code keeps its real value: a limit of 50.00 is now `5000`, a fee of 3.50 is now `350`.
- Shares and rates stay as they are (`0.05` is still 5%), and so do weights.
- New in module `money`: `pct(cents, rate)`, an amount times a rate, rounded half up: `floor(cents * rate + 0.5)` with
  floating point arithmetic. `avg(total, n)`, an average rounded half up: 0 when `n <= 0`, otherwise
  `floor((2 * total + n) / (2 * n))` in integers. `round2` goes away.
- Every amount that is a share of another (tax, discounts, commissions, refunds, half price, the per kilo part of a
  shipping cost) is computed with `pct` on the amount it applies to; a price after a share comes off is the price minus
  that share. Every average of money uses `avg`.
- `money.plain` and `money.fmt` take cents. People and files see the same text as before: `plain(1250)` is `"12.50"`,
  `fmt(1250)` is `"$12.50"`, `plain(7)` is `"0.07"`.
- Points are whole numbers as before. One point is still earned for every whole 10.00.
- Operating figures of the records that do not belong to sales (rent, wages, budgets, fees of contracts and the like)
  stay as they are.

## 2. Orders on hold

Fraud review can freeze an order. Add the status `Status.OnHold` (Python: `Status.ON_HOLD`), placed right after `Paid`.

- An order on hold behaves like a paid order everywhere, except for what follows.
- It does not move forward: its next status is itself. The warehouse does not pack it.
- People read it as `"On hold"`; the warehouse code is `"H"`; on the board it is `"amber"`; the customer is told
  `"<name>, your order <id> is on hold"`.
- New in module `orders`: `hold(order)` puts a paid order on hold and `release(order)` makes an order on hold paid again;
  other orders come back unchanged.
- Going from paid to on hold and from on hold to paid are valid steps.
- Wherever all the statuses are listed, it comes right after `Paid`.

## 3. First and last names

`Customer.name` is replaced by two text fields, `first_name` and `last_name`, in this order and in the same place
(other records have a `name` too: those stay).

- Wherever a customer's name is shown or used as a key, it is `"<first> <last>"`.
- Customers in alphabetical order: by last name, then by first name.
- A search by name matches when the text, in any case, is contained in the first or the last name.
- Initials are the first letter of the first name and the first letter of the last name, in capitals.
- The customer file gets the columns `first_name,last_name` in place of `name`, both when written and when read. A row
  with the old number of columns is not a customer.
- A customer's check reports `"first name is empty"` and `"last name is empty"`, in this order, in place of the old
  message.
- Two records are the same person when first name, last name (each in any case) and email match.

The sample data has to follow all three changes, with the same real prices and people. Everything else keeps working as
it does now.
