import { Cart, Line, discount, free_shipping_gap, item_count, line_total, subtotal, tax, total } from "./cart";
import { format_amount } from "./money";

/** Text of one line, e.g. 2 x Widget @ $3.50 = $7.00. */
export function line_text(line: Line): string {
  return `${line.qty} x ${line.item.name} @ ${format_amount(line.item.price)} = ${format_amount(line_total(line))}`;
}

export function render(cart: Cart, rate_bp: number): string {
  const lines: string[] = cart.lines.map(line_text);
  lines.push(`Subtotal: ${format_amount(subtotal(cart))}`);
  if (cart.code !== null) {
    lines.push(`Discount (${cart.code}): -${format_amount(discount(cart))}`);
  }
  lines.push(`Tax: ${format_amount(tax(cart, rate_bp))}`);
  lines.push(`Total: ${format_amount(total(cart, rate_bp))}`);
  const gap = free_shipping_gap(cart);
  lines.push(gap > 0.0 ? `Add ${format_amount(gap)} more for free shipping` : "Free shipping");
  return lines.join("\n");
}

/** One-line summary, e.g. 3 items, total $19.00. */
export function summary(cart: Cart, rate_bp: number): string {
  const n = item_count(cart);
  const noun = n === 1 ? "item" : "items";
  return `${n} ${noun}, total ${format_amount(total(cart, rate_bp))}`;
}
