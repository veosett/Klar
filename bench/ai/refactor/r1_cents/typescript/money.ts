/** Rounds a dollar amount to the nearest cent, halves up. */
export function round2(x: number): number {
  return Math.floor(x * 100.0 + 0.5) / 100.0;
}

/** Formats a dollar amount: 12.5 -> "$12.50", -2.5 -> "-$2.50". */
export function format_amount(amount: number): string {
  const sign = amount < 0.0 ? "-" : "";
  return `${sign}$${Math.abs(amount).toFixed(2)}`;
}

/** Parses "12.5", "12" or "$12.50" (surrounding spaces allowed) into dollars. */
export function parse_amount(text: string): number {
  let t = text.trim();
  if (t.startsWith("$")) {
    t = t.slice(1);
  }
  const parts = t.split(".");
  if (parts.length > 2 || !parts.every((p) => /^[0-9]+$/.test(p))) {
    throw new Error("invalid amount: " + text);
  }
  return parseFloat(t);
}
