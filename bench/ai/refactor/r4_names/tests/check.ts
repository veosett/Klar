import { Book, add_contact, count_contacts, empty_book, find_contact, remove_contact, sort_book, update_phone } from "./book";
import { Contact, initials, make_contact, with_city, with_phone } from "./contact";
import { csv_line, csv_lines, csv_text, display_line, display_list, parse_csv_line, read_csv } from "./export";
import { cities, contacts_in_city, find_by_phone, search_text } from "./search";

declare const process: { exit(code: number): never };

let failures = 0;

function show(x: unknown): string {
  return JSON.stringify(x);
}

function check(what: string, got: unknown, expected: unknown): void {
  if (show(got) !== show(expected)) {
    failures += 1;
    console.log(`FAIL: ${what}, got ${show(got)}, expected ${show(expected)}`);
  }
}

/** The message of the Error that `f` throws, or "no error". */
function error_of(f: () => unknown): string {
  try {
    f();
  } catch (e) {
    return e instanceof Error ? e.message : String(e);
  }
  return "no error";
}

function mk(first: string, last: string, phone: string, city: string): Contact {
  return make_contact(first, last, phone, city);
}

function ada(): Contact {
  return mk("Ada", "Lovelace", "5550101", "London");
}

function charles(): Contact {
  return mk("Charles", "Babbage", "5550102", "london");
}

function grace(): Contact {
  return mk("Grace", "Hopper", "5550103", "New York");
}

function people(): Book {
  return [
    ada(),
    charles(),
    grace(),
    mk("Alan", "Turing", "5550104", "Wilmslow"),
    mk("Anna", "Babbage", "5550105", "Paris"),
    mk("Augustus", "de Morgan", "5550106", "London"),
  ];
}

function full(book: readonly Contact[]): string[] {
  return book.map((c) => c.first + " " + c.last);
}

function phone_of(found: Contact | undefined): string {
  return found !== undefined ? found.phone : "none";
}

function bad(first: string, last: string, phone: string): string {
  return error_of(() => make_contact(first, last, phone, "X"));
}

const c = ada();
check("make_contact first", c.first, "Ada");
check("make_contact last", c.last, "Lovelace");
check("make_contact phone", c.phone, "5550101");
check("make_contact city", c.city, "London");
check("empty first name", bad("", "Lovelace", "5550101"), "first name must not be empty");
check("empty last name", bad("Ada", "", "5550101"), "last name must not be empty");
check("both names empty", bad("", "", "5550101"), "first name must not be empty");
check("empty last name before bad phone", bad("Ada", "", "abc"), "last name must not be empty");
check("bad phone", bad("Ada", "Lovelace", "abc"), "phone must be digits only");
check("empty phone", bad("Ada", "Lovelace", ""), "phone must be digits only");

// with_phone, with_city
check("with_phone revalidates", error_of(() => with_phone(ada(), "12x")), "phone must be digits only");
const moved = with_city(ada(), "Paris");
check("with_city keeps names", [moved.first, moved.last, moved.city], ["Ada", "Lovelace", "Paris"]);
const called = with_phone(grace(), "5559999");
check("with_phone keeps names", [called.first, called.last, called.phone], ["Grace", "Hopper", "5559999"]);

// initials
check("initials Ada Lovelace", initials(ada()), "A.L.");
check("initials Grace Hopper", initials(grace()), "G.H.");
check("initials lower case", initials(mk("grace", "hopper", "1", "")), "G.H.");
check("initials de Morgan", initials(mk("Augustus", "de Morgan", "5550106", "London")), "A.D.");

// find_contact
const book = people();
check("find Ada Lovelace", phone_of(find_contact(book, "Ada", "Lovelace")), "5550101");
check("find Anna Babbage", phone_of(find_contact(book, "Anna", "Babbage")), "5550105");
check("find Charles Babbage", phone_of(find_contact(book, "Charles", "Babbage")), "5550102");
check("find swapped names", find_contact(book, "Lovelace", "Ada"), undefined);
check("find first only matches", find_contact(book, "Ada", "Babbage"), undefined);
check("find exact last name", find_contact(book, "Ada", "Lovelace "), undefined);

// add_contact
const one = add_contact(empty_book(), ada());
check("add to empty book", count_contacts(one), 1);
check("add duplicate", error_of(() => add_contact(one, ada())), "duplicate contact: Ada Lovelace");
check("add duplicate other city", error_of(() => add_contact(one, with_city(ada(), "Paris"))),
      "duplicate contact: Ada Lovelace");
const two = add_contact(one, mk("Ada", "Byron", "5550107", "London"));
check("add same first name", full(two), ["Ada Lovelace", "Ada Byron"]);
const three = add_contact(two, mk("Augusta", "Lovelace", "5550108", "London"));
check("add same last name", count_contacts(three), 3);

// remove_contact
const without = remove_contact(book, "Charles", "Babbage");
check("remove Charles Babbage", full(without),
      ["Ada Lovelace", "Grace Hopper", "Alan Turing", "Anna Babbage", "Augustus de Morgan"]);
check("remove needs both names", count_contacts(remove_contact(book, "Charles", "Hopper")), 6);
check("remove swapped names", count_contacts(remove_contact(book, "Babbage", "Charles")), 6);
check("remove from empty book", count_contacts(remove_contact(empty_book(), "Ada", "Lovelace")), 0);

// update_phone
const updated = update_phone(people(), "Anna", "Babbage", "5559999");
check("update_phone target", phone_of(find_contact(updated, "Anna", "Babbage")), "5559999");
check("update_phone same last name", phone_of(find_contact(updated, "Charles", "Babbage")), "5550102");
check("update_phone keeps order", full(updated), full(people()));
check("update_phone unknown", error_of(() => update_phone(people(), "Ada", "Byron", "5559999")),
      "no such contact: Ada Byron");
check("update_phone bad phone", error_of(() => update_phone(people(), "Ada", "Lovelace", "12x")),
      "phone must be digits only");

// sort_book
check("sort_book", full(sort_book(people())), [
    "Anna Babbage",
    "Charles Babbage",
    "Augustus de Morgan",
    "Grace Hopper",
    "Ada Lovelace",
    "Alan Turing",
]);
check("sort_book empty", full(sort_book(empty_book())), []);

// search
check("search last name", full(search_text(book, "love")), ["Ada Lovelace"]);
check("search first name, upper case", full(search_text(book, "ADA")), ["Ada Lovelace"]);
check("search hop", full(search_text(book, "hop")), ["Grace Hopper"]);
check("search bab", full(search_text(book, "bab")), ["Charles Babbage", "Anna Babbage"]);
check("search an", full(search_text(book, "an")), ["Alan Turing", "Anna Babbage", "Augustus de Morgan"]);
check("search across names", full(search_text(book, "ada l")), []);
check("search across names, full", full(search_text(book, "ada lovelace")), []);
check("search no match", full(search_text(book, "xyz")), []);
check("search empty text", search_text(book, "").length, 6);
check("contacts_in_city", full(contacts_in_city(book, "LONDON")), ["Ada Lovelace", "Charles Babbage", "Augustus de Morgan"]);
check("contacts_in_city none", full(contacts_in_city(book, "Berlin")), []);
check("find_by_phone", phone_of(find_by_phone(book, "5550103")), "5550103");
check("find_by_phone none", find_by_phone(book, "1"), undefined);
check("cities", cities(book), ["London", "New York", "Paris", "Wilmslow", "london"]);

// export
check("csv_line", csv_line(ada()), "Lovelace,Ada,5550101,London");
check("csv_lines", csv_lines([ada(), grace()]), [
    "last,first,phone,city",
    "Lovelace,Ada,5550101,London",
    "Hopper,Grace,5550103,New York",
]);
check("csv_lines empty", csv_lines(empty_book()), ["last,first,phone,city"]);
check("csv_text", csv_text([ada()]), "last,first,phone,city\nLovelace,Ada,5550101,London\n");
check("parse_csv_line", parse_csv_line("Lovelace,Ada,5550101,London"), ada());
check("parse_csv_line 3 fields", error_of(() => parse_csv_line("Ada Lovelace,5550101,London")),
      "bad csv line: Ada Lovelace,5550101,London");
check("parse_csv_line 5 fields", error_of(() => parse_csv_line("Lovelace,Ada,5550101,London,UK")),
      "bad csv line: Lovelace,Ada,5550101,London,UK");
check("parse_csv_line empty first", error_of(() => parse_csv_line("Lovelace,,5550101,London")),
      "first name must not be empty");
check("parse_csv_line empty last", error_of(() => parse_csv_line(",Ada,5550101,London")),
      "last name must not be empty");
check("parse_csv_line bad phone", error_of(() => parse_csv_line("Lovelace,Ada,55x,London")),
      "phone must be digits only");
check("read_csv round trip", read_csv(csv_lines(people())), people());
check("read_csv empty book", read_csv(csv_lines(empty_book())), empty_book());
check("read_csv old header", error_of(() => read_csv(["name,phone,city", "Ada Lovelace,5550101,London"])),
      "bad csv header");
check("read_csv no lines", error_of(() => read_csv([])), "bad csv header");
check("read_csv duplicate",
      error_of(() => read_csv(["last,first,phone,city", "Lovelace,Ada,5550101,London", "Lovelace,Ada,5550102,Paris"])),
      "duplicate contact: Ada Lovelace");
check("read_csv bad line", error_of(() => read_csv(["last,first,phone,city", "Lovelace,Ada"])),
      "bad csv line: Lovelace,Ada");
check("display_line", display_line(ada()), "Lovelace, Ada — 5550101");
check("display_list", display_list([ada(), grace()]), ["Lovelace, Ada — 5550101", "Hopper, Grace — 5550103"]);
check("display_list empty", display_list(empty_book()), []);
check("display_list sorted first", display_list(sort_book(people()))[0], "Babbage, Anna — 5550105");

if (failures > 0) {
  process.exit(1);
}
