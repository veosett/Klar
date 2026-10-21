type Shape =
  | { kind: "circle"; radius: number }
  | { kind: "square"; side: number }
  | { kind: "triangle"; base: number; height: number };

function area(s: Shape): number {
  switch (s.kind) { // BUG: triangle is not handled
    case "circle":
      return 3.14159 * s.radius * s.radius;
    case "square":
      return s.side * s.side;
  }
}

console.log(area({ kind: "triangle", base: 4, height: 3 }).toFixed(1));
