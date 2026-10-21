const start = performance.now();
const parts = Array.from({ length: 100000 }, (_, i) => `item${i}`);
const joined = parts.join(",");
const back = joined.split(",");
const sevens = back.filter((s) => s.endsWith("7")).length;
const elapsed = performance.now() - start;
console.log(`result=${sevens},${joined.length}`);
console.log(`time_ms=${elapsed.toFixed(3)}`);
