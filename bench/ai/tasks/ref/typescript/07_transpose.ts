export function transpose(m: number[][]): number[][] {
  if (m.length === 0) return [];
  return m[0].map((_, j) => m.map((row) => row[j]));
}
