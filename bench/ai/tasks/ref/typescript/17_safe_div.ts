export function divide_all(xs: number[], ys: number[]): number[] {
  return xs.map((x, i) => {
    if (ys[i] === 0) throw new Error(`division by zero at index ${i}`);
    return Math.trunc(x / ys[i]);
  });
}
