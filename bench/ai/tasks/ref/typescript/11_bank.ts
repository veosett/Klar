export function run_ops(ops: string[]): number {
  let balance = 0;
  ops.forEach((op, i) => {
    const parts = op.split(" ");
    if (parts.length !== 2 || (parts[0] !== "deposit" && parts[0] !== "withdraw") || !/^[0-9]+$/.test(parts[1])) {
      throw new Error(`bad op at op ${i + 1}`);
    }
    const n = Number(parts[1]);
    if (parts[0] === "deposit") balance += n;
    else if (balance - n < 0) throw new Error(`insufficient funds at op ${i + 1}`);
    else balance -= n;
  });
  return balance;
}
