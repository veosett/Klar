function finalPrice(price: number, discountPercent: number, taxPercent: number): number {
  return Math.floor(Math.floor((price * (100 - discountPercent)) / 100) * (100 + taxPercent) / 100);
}

console.log(finalPrice(200, 20, 10)); // BUG: tax and discount swapped (should be discount 10, tax 20)
