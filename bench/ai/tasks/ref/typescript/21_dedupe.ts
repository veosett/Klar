export function dedupe(xs: number[]): number[] {
  return [...new Set(xs)];
}
