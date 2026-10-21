function nextYearAge(ages: Map<string, number>, name: string): number {
  return ages.get(name) + 1; // BUG: the key may be missing
}

const ages = new Map<string, number>([["ann", 31], ["bob", 42]]);
console.log(nextYearAge(ages, "cat"));
