import { Contact, with_phone } from "./contact";

/** The contacts in the order they were added (until `sort_book`). */
export type Book = readonly Contact[];

export function empty_book(): Book {
  return [];
}

export function count_contacts(book: Book): number {
  return book.length;
}

/** The contact with exactly this name, if there is one. */
export function find_contact(book: Book, name: string): Contact | undefined {
  return book.find((c) => c.name === name);
}

/** Adds a contact; a second contact with the same name is refused (Error). */
export function add_contact(book: Book, c: Contact): Book {
  if (find_contact(book, c.name) !== undefined) {
    throw new Error("duplicate contact: " + c.name);
  }
  return [...book, c];
}

/** Removes the contact with this name; the book is unchanged if there is none. */
export function remove_contact(book: Book, name: string): Book {
  return book.filter((c) => c.name !== name);
}

/** Gives the contact with this name a new phone number. */
export function update_phone(book: Book, name: string, phone: string): Book {
  const found = find_contact(book, name);
  if (found === undefined) {
    throw new Error("no such contact: " + name);
  }
  const updated = with_phone(found, phone);
  return book.map((c) => (c.name === name ? updated : c));
}

function compare(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

/** The book ordered by name, ignoring case. */
export function sort_book(book: Book): Book {
  return [...book].sort((a, b) => compare(a.name.toLowerCase(), b.name.toLowerCase()));
}
