import { format_amount } from "./money";

export interface Item {
  readonly name: string;
  readonly price: number;
}

/** Builds a validated item: the name must not be blank and the price must be positive. */
export function make_item(name: string, price: number): Item {
  if (name.trim() === "") {
    throw new Error("empty name");
  }
  if (price <= 0.0) {
    throw new Error(`invalid price for ${name}`);
  }
  return { name, price };
}

export function default_catalog(): Item[] {
  return [
    { name: "Widget", price: 3.5 },
    { name: "Gadget", price: 12.5 },
    { name: "Gizmo", price: 49.99 },
    { name: "Cable", price: 7.25 },
    { name: "Case", price: 24.0 },
  ];
}

export function find_item(items: Item[], name: string): Item | null {
  return items.find((i) => i.name === name) ?? null;
}

/** Cheapest first. */
export function sorted_by_price(items: Item[]): Item[] {
  return [...items].sort((a, b) => a.price - b.price);
}

export function cheapest(items: Item[]): Item | null {
  return sorted_by_price(items)[0] ?? null;
}

/** One line per item: "Widget - $3.50". */
export function catalog_text(items: Item[]): string {
  return items.map((i) => `${i.name} - ${format_amount(i.price)}`).join("\n");
}
