export function group_anagrams(words: string[]): string[][] {
  const groups = new Map<string, string[]>();
  for (const w of words) {
    const key = [...w].sort().join("");
    groups.set(key, [...(groups.get(key) ?? []), w]);
  }
  return [...groups.values()].map((g) => [...g].sort()).sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
}
