function average(xs: number[]): number {
  return Math.floor(xs.reduce((a, b) => a + b, 0) / xs.length); // BUG: the list may be empty
}

console.log(average([]));
