export function common_prefix(words: string[]): string {
  if (words.length === 0) return "";
  let p = words[0];
  for (const w of words.slice(1)) {
    while (!w.startsWith(p)) p = p.slice(0, -1);
  }
  return p;
}
