export function histogram(counts: Record<string, number>): string[] {
  return Object.keys(counts).sort().map((k) => `${k}: ${"*".repeat(counts[k])}`);
}
