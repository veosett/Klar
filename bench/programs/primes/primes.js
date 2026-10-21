function isPrime(n) {
  if (n < 2) return false;
  if (n % 2 === 0) return n === 2;
  for (let d = 3; d * d <= n; d += 2) if (n % d === 0) return false;
  return true;
}
const start = performance.now();
let count = 0;
for (let n = 0; n < 30000; n++) if (isPrime(n)) count++;
const elapsed = performance.now() - start;
console.log(`result=${count}`);
console.log(`time_ms=${elapsed.toFixed(3)}`);
