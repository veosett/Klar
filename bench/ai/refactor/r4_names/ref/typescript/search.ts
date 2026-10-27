import { Book } from "./book";
import { Contact } from "./contact";

/** Contacts whose first or last name contains `text`, ignoring case. */
export function search_text(book: Book, text: string): Contact[] {
  const needle = text.toLowerCase();
  return book.filter((c) => c.first.toLowerCase().includes(needle) || c.last.toLowerCase().includes(needle));
}

/** Contacts living in `city`, ignoring case. */
export function contacts_in_city(book: Book, city: string): Contact[] {
  const wanted = city.toLowerCase();
  return book.filter((c) => c.city.toLowerCase() === wanted);
}

/** The contact with this phone number, if any. */
export function find_by_phone(book: Book, phone: string): Contact | undefined {
  return book.find((c) => c.phone === phone);
}

/** Every city in the book once, in alphabetical order. */
export function cities(book: Book): string[] {
  return [...new Set(book.map((c) => c.city))].sort();
}
