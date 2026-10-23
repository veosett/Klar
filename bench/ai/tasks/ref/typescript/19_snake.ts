export function camel_to_snake(s: string): string {
  let out = "";
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (c >= "A" && c <= "Z") out += (i > 0 ? "_" : "") + c.toLowerCase();
    else out += c;
  }
  return out;
}
