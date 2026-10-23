export function caesar(text: string, shift: number): string {
  const rot = (c: string, base: number) => String.fromCharCode(((((c.charCodeAt(0) - base + shift) % 26) + 26) % 26) + base);
  let out = "";
  for (const c of text) {
    if (c >= "a" && c <= "z") out += rot(c, 97);
    else if (c >= "A" && c <= "Z") out += rot(c, 65);
    else out += c;
  }
  return out;
}
