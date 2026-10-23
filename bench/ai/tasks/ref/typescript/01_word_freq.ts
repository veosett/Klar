export function word_freq(text: string): Record<string, number> {
  const out: Record<string, number> = {};
  for (const raw of text.split(" ")) {
    if (raw === "") continue;
    const w = raw.toLowerCase();
    out[w] = (out[w] ?? 0) + 1;
  }
  return out;
}
