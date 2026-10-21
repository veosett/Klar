const start = performance.now();
let total = 0;
for (let i = 0; i < 300000; i++) total = (total + i * i) % 1000007;
const elapsed = performance.now() - start;
console.log(`result=${total}`);
console.log(`time_ms=${elapsed.toFixed(3)}`);
