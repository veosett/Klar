import { format_amount } from "./money";

export interface Item {
  readonly name: string;
  readonly price_cents: number;
}

/** Builds a validated item: the name must not be blank and the price must be positive. */
export function make_item(name: string, price_cents: number): Item {
  if (name.trim() === "") {
    throw new Error("empty name");
  }
  if (price_cents <= 0) {
    throw new Error(`invalid price for ${name}`);
  }
  return { name, price_cents };
}

export function default_catalog(): Item[] {
  return [
    { name: "Widget", price_cents: 350 },
    { name: "Gadget", price_cents: 1250 },
    { name: "Gizmo", price_cents: 4999 },
    { name: "Cable", price_cents: 725 },
    { name: "Case", price_cents: 2400 },
  ];
}

export function find_item(items: Item[], name: string): Item | null {
  return items.find((i) => i.name === name) ?? null;
}

/** Cheapest first. */
export function sorted_by_price(items: Item[]): Item[] {
  return [...items].sort((a, b) => a.price_cents - b.price_cents);
}

export function cheapest(items: Item[]): Item | null {
  return sorted_by_price(items)[0] ?? null;
}

/** One line per item: "Widget - $3.50". */
export function catalog_text(items: Item[]): string {
  return items.map((i) => `${i.name} - ${format_amount(i.price_cents)}`).join("\n");
}
