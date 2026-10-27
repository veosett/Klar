/** n / d rounded to the nearest integer, halves up (n >= 0, d > 0). */
export function round_div(n: number, d: number): number {
  return Math.floor((2 * n + d) / (2 * d));
}

/** Formats an amount in cents: 1250 -> "$12.50", -250 -> "-$2.50". */
export function format_amount(cents: number): string {
  const sign = cents < 0 ? "-" : "";
  const abs_cents = Math.abs(cents);
  const frac = String(abs_cents % 100).padStart(2, "0");
  return `${sign}$${Math.floor(abs_cents / 100)}.${frac}`;
}

/** Parses "12.5", "12" or "$12.50" (surrounding spaces allowed, at most 2 decimals) into cents. */
export function parse_amount(text: string): number {
  let t = text.trim();
  if (t.startsWith("$")) {
    t = t.slice(1);
  }
  const parts = t.split(".");
  if (parts.length > 2 || !parts.every((p) => /^[0-9]+$/.test(p))) {
    throw new Error("invalid amount: " + text);
  }
  const frac = parts.length === 2 ? parts[1] : "";
  if (frac.length > 2) {
    throw new Error("invalid amount: " + text);
  }
  return parseInt(parts[0], 10) * 100 + parseInt(frac.padEnd(2, "0"), 10);
}
