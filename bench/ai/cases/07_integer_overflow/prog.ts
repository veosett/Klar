function factorial(n: number): number {
  let r = 1;
  for (let i = 2; i <= n; i++) {
    r = r * i; // BUG?: overflows in most languages
  }
  return r;
}

console.log(String(factorial(25)));
