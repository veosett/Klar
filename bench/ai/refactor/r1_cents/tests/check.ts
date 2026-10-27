import { format_amount, parse_amount } from "./money";
import { Item, make_item, default_catalog, find_item, sorted_by_price, cheapest, catalog_text } from "./catalog";
import { Cart, Line, FREE_SHIPPING_MIN, new_cart, add_line, apply_code, discount_percent, item_count, line_total,
  largest_line, subtotal, discount, tax, total, free_shipping_gap } from "./cart";
import { line_text, render, summary } from "./receipt";

declare const process: { exit(code: number): never };

let failures = 0;

function check(label: string, thunk: () => string | number, expected: string | number): void {
  let got: string | number;
  try {
    got = thunk();
  } catch (e) {
    got = "Error: " + (e as Error).message;
  }
  if (got !== expected) {
    failures += 1;
    console.log(`FAIL: ${label}, got ${JSON.stringify(got)}, expected ${JSON.stringify(expected)}`);
  }
}

function it(name: string, cents: number): Item {
  return { name, price_cents: cents };
}

function ln(item: Item, qty: number): Line {
  return { item, qty };
}

function cart_of(parts: Line[], code_text: string): Cart {
  return { lines: parts, code: code_text !== "" ? code_text : null };
}

function one(cents: number, code_text: string): Cart {
  return cart_of([ln(it("X", cents), 1)], code_text);
}

function cart_a(code_text: string): Cart {
  return cart_of([ln(it("Widget", 350), 2), ln(it("Gadget", 1250), 1)], code_text);
}

function cat(): Item[] {
  return default_catalog();
}

function attempt(f: () => string): string {
  try {
    return f();
  } catch (e) {
    return (e as Error).message;
  }
}

function pa(text: string): string {
  return attempt(() => String(parse_amount(text)));
}

function item_msg(name: string, cents: number): string {
  return attempt(() => {
    const i = make_item(name, cents);
    return `ok ${i.name} ${i.price_cents}`;
  });
}

function add_msg(c: Cart, item: Item, qty: number): string {
  return attempt(() => `ok ${add_line(c, item, qty).lines.length}`);
}

function code_msg(c: Cart, code_text: string): string {
  return attempt(() => {
    apply_code(c, code_text);
    return "ok";
  });
}

function name_of_line(l: Line | null): string {
  return l === null ? "none" : l.item.name;
}

function largest_line_or_zero(c: Cart): Line {
  return largest_line(c) ?? ln(it("none", 0), 0);
}

function name_of_item(i: Item | null): string {
  return i === null ? "none" : i.name;
}

function price_of(i: Item | null): number {
  return i === null ? -1 : i.price_cents;
}

function names(items: Item[]): string {
  return items.map((i) => i.name).join(",");
}

function pct(code_text: string): number {
  return discount_percent(code_text) ?? -1;
}

check("01 format_amount(0)", () => format_amount(0), "$0.00");
check("02 format_amount(5)", () => format_amount(5), "$0.05");
check("03 format_amount(100)", () => format_amount(100), "$1.00");
check("04 format_amount(1250)", () => format_amount(1250), "$12.50");
check("05 format_amount(123456)", () => format_amount(123456), "$1234.56");
check("06 format_amount(-250)", () => format_amount(-250), "-$2.50");
check("07 format_amount(-5)", () => format_amount(-5), "-$0.05");
check("08 format_amount(4999)", () => format_amount(4999), "$49.99");
check("09 pa('12.5')", () => pa("12.5"), "1250");
check("10 pa('12.50')", () => pa("12.50"), "1250");
check("11 pa('12')", () => pa("12"), "1200");
check("12 pa('$3.99')", () => pa("$3.99"), "399");
check("13 pa('  $0.05 ')", () => pa("  $0.05 "), "5");
check("14 pa('0')", () => pa("0"), "0");
check("15 pa('7.05')", () => pa("7.05"), "705");
check("16 pa('0.5')", () => pa("0.5"), "50");
check("17 pa('12.345')", () => pa("12.345"), "invalid amount: 12.345");
check("18 pa('abc')", () => pa("abc"), "invalid amount: abc");
check("19 pa('')", () => pa(""), "invalid amount: ");
check("20 pa('-1')", () => pa("-1"), "invalid amount: -1");
check("21 pa('1.2.3')", () => pa("1.2.3"), "invalid amount: 1.2.3");
check("22 pa('.5')", () => pa(".5"), "invalid amount: .5");
check("23 pa('5.')", () => pa("5."), "invalid amount: 5.");
check("24 item_msg('Pen', 0)", () => item_msg("Pen", 0), "invalid price for Pen");
check("25 item_msg('Pen', -5)", () => item_msg("Pen", -5), "invalid price for Pen");
check("26 item_msg('', 100)", () => item_msg("", 100), "empty name");
check("27 item_msg('Pen', 199)", () => item_msg("Pen", 199), "ok Pen 199");
check("28 price_of(find_item(cat(), 'Gizmo'))", () => price_of(find_item(cat(), "Gizmo")), 4999);
check("29 price_of(find_item(cat(), 'Cable'))", () => price_of(find_item(cat(), "Cable")), 725);
check("30 price_of(find_item(cat(), 'Case'))", () => price_of(find_item(cat(), "Case")), 2400);
check("31 name_of_item(find_item(cat(), 'Nope'))", () => name_of_item(find_item(cat(), "Nope")), "none");
check("32 names(sorted_by_price(cat()))", () => names(sorted_by_price(cat())), "Widget,Cable,Gadget,Case,Gizmo");
check("33 names(sorted_by_price([it('A', 999), it('B', 1000), it('C', 98)]))", () => names(sorted_by_price([it("A", 999), it("B", 1000), it("C", 98)])), "C,A,B");
check("34 name_of_item(cheapest(cat()))", () => name_of_item(cheapest(cat())), "Widget");
check("35 name_of_item(cheapest([it('A', 999), it('B', 1000), it('C', 98)]))", () => name_of_item(cheapest([it("A", 999), it("B", 1000), it("C", 98)])), "C");
check("36 catalog_text(cat())", () => catalog_text(cat()), "Widget - $3.50\nGadget - $12.50\nGizmo - $49.99\nCable - $7.25\nCase - $24.00");
check("37 FREE_SHIPPING_MIN", () => FREE_SHIPPING_MIN, 5000);
check("38 line_total(ln(it('W', 350), 3))", () => line_total(ln(it("W", 350), 3)), 1050);
check("39 subtotal(cart_a(''))", () => subtotal(cart_a("")), 1950);
check("40 subtotal(cart_of([], ''))", () => subtotal(cart_of([], "")), 0);
check("41 item_count(cart_a(''))", () => item_count(cart_a("")), 3);
check("42 name_of_line(largest_line(cart_a('')))", () => name_of_line(largest_line(cart_a(""))), "Gadget");
check("43 line_total(largest_line_or_zero(cart_a('')))", () => line_total(largest_line_or_zero(cart_a(""))), 1250);
check("44 add_msg(cart_a(''), it('X', 100), 0)", () => add_msg(cart_a(""), it("X", 100), 0), "invalid quantity: 0");
check("45 add_msg(cart_a(''), it('X', 100), 100)", () => add_msg(cart_a(""), it("X", 100), 100), "invalid quantity: 100");
check("46 add_msg(cart_a(''), it('X', 100), 5)", () => add_msg(cart_a(""), it("X", 100), 5), "ok 3");
check("47 code_msg(cart_a(''), 'NOPE')", () => code_msg(cart_a(""), "NOPE"), "unknown code: NOPE");
check("48 code_msg(cart_a(''), 'HALF')", () => code_msg(cart_a(""), "HALF"), "ok");
check("49 pct('VIP15')", () => pct("VIP15"), 15);
check("50 pct('x')", () => pct("x"), -1);
check("51 discount(cart_a(''))", () => discount(cart_a("")), 0);
check("52 discount(cart_a('SAVE10'))", () => discount(cart_a("SAVE10")), 195);
check("53 discount(one(1050, 'WELCOME5'))", () => discount(one(1050, "WELCOME5")), 53);
check("54 discount(one(990, 'WELCOME5'))", () => discount(one(990, "WELCOME5")), 50);
check("55 discount(one(330, 'VIP15'))", () => discount(one(330, "VIP15")), 50);
check("56 discount(one(1001, 'HALF'))", () => discount(one(1001, "HALF")), 501);
check("57 discount(one(1005, 'SAVE10'))", () => discount(one(1005, "SAVE10")), 101);
check("58 discount(one(1004, 'SAVE10'))", () => discount(one(1004, "SAVE10")), 100);
check("59 discount(one(1, 'WELCOME5'))", () => discount(one(1, "WELCOME5")), 0);
check("60 discount(cart_of([ln(it('A', 333), 3)], 'VIP15'))", () => discount(cart_of([ln(it("A", 333), 3)], "VIP15")), 150);
check("61 tax(one(1000, ''), 825)", () => tax(one(1000, ""), 825), 83);
check("62 tax(one(200, ''), 725)", () => tax(one(200, ""), 725), 15);
check("63 tax(one(997, ''), 825)", () => tax(one(997, ""), 825), 82);
check("64 tax(cart_a(''), 825)", () => tax(cart_a(""), 825), 161);
check("65 tax(cart_a('SAVE10'), 825)", () => tax(cart_a("SAVE10"), 825), 145);
check("66 tax(one(1001, 'HALF'), 1000)", () => tax(one(1001, "HALF"), 1000), 50);
check("67 tax(one(1010, ''), 500)", () => tax(one(1010, ""), 500), 51);
check("68 tax(one(1010, ''), 0)", () => tax(one(1010, ""), 0), 0);
check("69 tax(one(1, ''), 825)", () => tax(one(1, ""), 825), 0);
check("70 total(cart_a(''), 825)", () => total(cart_a(""), 825), 2111);
check("71 total(cart_a('SAVE10'), 825)", () => total(cart_a("SAVE10"), 825), 1900);
check("72 total(one(1050, 'WELCOME5'), 825)", () => total(one(1050, "WELCOME5"), 825), 1079);
check("73 total(cart_of([], ''), 825)", () => total(cart_of([], ""), 825), 0);
check("74 free_shipping_gap(cart_a('SAVE10'))", () => free_shipping_gap(cart_a("SAVE10")), 3245);
check("75 free_shipping_gap(one(10000, 'HALF'))", () => free_shipping_gap(one(10000, "HALF")), 0);
check("76 free_shipping_gap(one(9998, 'HALF'))", () => free_shipping_gap(one(9998, "HALF")), 1);
check("77 free_shipping_gap(one(5000, ''))", () => free_shipping_gap(one(5000, "")), 0);
check("78 free_shipping_gap(one(5349, 'VIP15'))", () => free_shipping_gap(one(5349, "VIP15")), 453);
check("79 free_shipping_gap(cart_of([], ''))", () => free_shipping_gap(cart_of([], "")), 5000);
check("80 line_text(ln(it('Widget', 350), 2))", () => line_text(ln(it("Widget", 350), 2)), "2 x Widget @ $3.50 = $7.00");
check("81 render(cart_a('SAVE10'), 825)", () => render(cart_a("SAVE10"), 825), "2 x Widget @ $3.50 = $7.00\n1 x Gadget @ $12.50 = $12.50\nSubtotal: $19.50\nDiscount (SAVE10): -$1.95\nTax: $1.45\nTotal: $19.00\nAdd $32.45 more for free shipping");
check("82 render(cart_a(''), 0)", () => render(cart_a(""), 0), "2 x Widget @ $3.50 = $7.00\n1 x Gadget @ $12.50 = $12.50\nSubtotal: $19.50\nTax: $0.00\nTotal: $19.50\nAdd $30.50 more for free shipping");
check("83 render(cart_of([], ''), 825)", () => render(cart_of([], ""), 825), "Subtotal: $0.00\nTax: $0.00\nTotal: $0.00\nAdd $50.00 more for free shipping");
check("84 render(cart_of([ln(it('Gizmo', 4999), 1), ln(it('Cable', 725), 2)], ''), 825)", () => render(cart_of([ln(it("Gizmo", 4999), 1), ln(it("Cable", 725), 2)], ""), 825), "1 x Gizmo @ $49.99 = $49.99\n2 x Cable @ $7.25 = $14.50\nSubtotal: $64.49\nTax: $5.32\nTotal: $69.81\nFree shipping");
check("85 summary(cart_a('SAVE10'), 825)", () => summary(cart_a("SAVE10"), 825), "3 items, total $19.00");
check("86 summary(one(350, ''), 825)", () => summary(one(350, ""), 825), "1 item, total $3.79");
check("87 summary(cart_of([], ''), 825)", () => summary(cart_of([], ""), 825), "0 items, total $0.00");

process.exit(failures > 0 ? 1 : 0);
