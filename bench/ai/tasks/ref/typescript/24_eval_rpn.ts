export function eval_rpn(expr: string): number {
  const stack: number[] = [];
  for (const tok of expr.split(" ").filter((t) => t !== "")) {
    if (["+", "-", "*", "/"].includes(tok)) {
      if (stack.length < 2) throw new Error("stack underflow");
      const b = stack.pop()!;
      const a = stack.pop()!;
      if (tok === "+") stack.push(a + b);
      else if (tok === "-") stack.push(a - b);
      else if (tok === "*") stack.push(a * b);
      else {
        if (b === 0) throw new Error("division by zero");
        stack.push(Math.trunc(a / b));
      }
    } else if (/^-?[0-9]+$/.test(tok)) stack.push(Number(tok));
    else throw new Error(`bad token ${tok}`);
  }
  if (stack.length !== 1) throw new Error("bad expression");
  return stack[0];
}
