export function fib_mod(n: number, m: number): number {
  let a = 0;
  let b = 1 % m;
  for (let i = 0; i < n; i++) {
    const t = (a + b) % m;
    a = b;
    b = t;
  }
  return a % m;
}
