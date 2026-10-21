const start = performance.now();
let inside = 0;
for (let y = 0; y < 60; y++) {
  for (let x = 0; x < 120; x++) {
    const cr = x / 120.0 * 3.5 - 2.5;
    const ci = y / 60.0 * 2.0 - 1.0;
    let zr = 0.0, zi = 0.0, k = 0;
    while (k < 50 && zr * zr + zi * zi <= 4.0) {
      const t = zr * zr - zi * zi + cr;
      zi = 2.0 * zr * zi + ci;
      zr = t;
      k++;
    }
    if (k === 50) inside++;
  }
}
const elapsed = performance.now() - start;
console.log(`result=${inside}`);
console.log(`time_ms=${elapsed.toFixed(3)}`);
