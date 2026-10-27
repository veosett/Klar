import { Item } from "./catalog";
import { round2 } from "./money";

/** Minimum amount (after discount, before tax) for free shipping: $50.00. */
export const FREE_SHIPPING_MIN: number = 50.0;

export interface Line {
  readonly item: Item;
  readonly qty: number;
}

export interface Cart {
  readonly lines: readonly Line[];
  readonly code: string | null;
}

export function new_cart(): Cart {
  return { lines: [], code: null };
}

export function add_line(cart: Cart, item: Item, qty: number): Cart {
  if (qty < 1 || qty > 99) {
    throw new Error(`invalid quantity: ${qty}`);
  }
  return { ...cart, lines: [...cart.lines, { item, qty }] };
}

const PERCENTS: Record<string, number> = { SAVE10: 10, WELCOME5: 5, VIP15: 15, HALF: 50 };

/** Percentage taken off by a discount code, null for an unknown code. */
export function discount_percent(code: string): number | null {
  return Object.prototype.hasOwnProperty.call(PERCENTS, code) ? PERCENTS[code] : null;
}

export function apply_code(cart: Cart, code: string): Cart {
  if (discount_percent(code) === null) {
    throw new Error(`unknown code: ${code}`);
  }
  return { ...cart, code };
}

export function item_count(cart: Cart): number {
  return cart.lines.reduce((acc, l) => acc + l.qty, 0);
}

export function line_total(line: Line): number {
  return line.item.price * line.qty;
}

export function largest_line(cart: Cart): Line | null {
  let best: Line | null = null;
  for (const l of cart.lines) {
    if (best === null || line_total(l) > line_total(best)) {
      best = l;
    }
  }
  return best;
}

export function subtotal(cart: Cart): number {
  return cart.lines.reduce((acc, l) => acc + line_total(l), 0.0);
}

/** The discount for the cart's code, rounded to the cent (0 without a code). */
export function discount(cart: Cart): number {
  const percent = cart.code === null ? 0 : (discount_percent(cart.code) ?? 0);
  return round2((subtotal(cart) * percent) / 100.0);
}

/** Tax on the subtotal after the discount; the rate is in basis points (825 = 8.25%). */
export function tax(cart: Cart, rate_bp: number): number {
  const taxable = subtotal(cart) - discount(cart);
  return round2((taxable * rate_bp) / 10000.0);
}

export function total(cart: Cart, rate_bp: number): number {
  return subtotal(cart) - discount(cart) + tax(cart, rate_bp);
}

/** How much more must be bought (after discount) to get free shipping. */
export function free_shipping_gap(cart: Cart): number {
  const net = subtotal(cart) - discount(cart);
  if (net >= FREE_SHIPPING_MIN) {
    return 0.0;
  }
  return round2(FREE_SHIPPING_MIN - net);
}
