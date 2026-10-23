export function merge_intervals(xs: number[][]): number[][] {
  const sorted = [...xs].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const out: number[][] = [];
  for (const [a, b] of sorted) {
    const last = out[out.length - 1];
    if (last && a <= last[1]) last[1] = Math.max(last[1], b);
    else out.push([a, b]);
  }
  return out;
}
