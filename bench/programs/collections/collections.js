const start = performance.now();
const ys = Array.from({ length: 200000 }, (_, x) => (x * 7919) % 10007)
  .filter((x) => x % 2 === 0)
  .sort((a, b) => a - b);
const total = ys.reduce((a, b) => a + b, 0);
const median = ys[Math.floor(ys.length / 2)];
const elapsed = performance.now() - start;
console.log(`result=${ys.length},${total},${median}`);
console.log(`time_ms=${elapsed.toFixed(3)}`);
