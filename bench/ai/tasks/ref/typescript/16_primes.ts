export function primes_up_to(n: number): number[] {
  const out: number[] = [];
  const composite = new Array<boolean>(Math.max(n + 1, 0)).fill(false);
  for (let i = 2; i <= n; i++) {
    if (composite[i]) continue;
    out.push(i);
    for (let j = i * i; j <= n; j += i) composite[j] = true;
  }
  return out;
}
