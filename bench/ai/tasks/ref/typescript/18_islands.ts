export function count_islands(grid: string[]): number {
  const seen = new Set<string>();
  let count = 0;
  for (let r = 0; r < grid.length; r++) {
    for (let c = 0; c < grid[r].length; c++) {
      if (grid[r][c] !== "#" || seen.has(`${r},${c}`)) continue;
      count++;
      const stack: [number, number][] = [[r, c]];
      seen.add(`${r},${c}`);
      while (stack.length > 0) {
        const [y, x] = stack.pop()!;
        for (const [dy, dx] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
          const ny = y + dy;
          const nx = x + dx;
          if (ny >= 0 && ny < grid.length && nx >= 0 && nx < grid[ny].length && grid[ny][nx] === "#" &&
            !seen.has(`${ny},${nx}`)) {
            seen.add(`${ny},${nx}`);
            stack.push([ny, nx]);
          }
        }
      }
    }
  }
  return count;
}
