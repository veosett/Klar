function fact(n: number): number {
  return n * fact(n - 1); // BUG: no base case
}

console.log(fact(5));
