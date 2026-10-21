function fib(n) { return n < 2 ? n : fib(n - 1) + fib(n - 2); }
const start = performance.now();
const r = fib(25);
const elapsed = performance.now() - start;
console.log(`result=${r}`);
console.log(`time_ms=${elapsed.toFixed(3)}`);
