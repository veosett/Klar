function doubleQuantity(text: string): number {
  const qty = parseInt(text, 10);
  return qty * 2; // BUG: the text may not be a number
}

console.log(doubleQuantity("12a"));
