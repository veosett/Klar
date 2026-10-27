import { Book, add_contact, empty_book } from "./book";
import { Contact, make_contact } from "./contact";

const CSV_HEADER = "name,phone,city";

/** One CSV line; no quoting or escaping. */
export function csv_line(c: Contact): string {
  return c.name + "," + c.phone + "," + c.city;
}

/** The header line followed by one line per contact, in book order. */
export function csv_lines(book: Book): string[] {
  return [CSV_HEADER, ...book.map(csv_line)];
}

/** The whole CSV file as one text, one line per row. */
export function csv_text(book: Book): string {
  return csv_lines(book).join("\n") + "\n";
}

/** Reads one CSV line (as written by `csv_line`) back into a contact. */
export function parse_csv_line(line: string): Contact {
  const fields = line.split(",");
  if (fields.length !== 3) {
    throw new Error("bad csv line: " + line);
  }
  return make_contact(fields[0], fields[1], fields[2]);
}

/** Reads the output of `csv_lines` back into a book; stops at the first bad line. */
export function read_csv(lines: readonly string[]): Book {
  if (lines.length === 0 || lines[0] !== CSV_HEADER) {
    throw new Error("bad csv header");
  }
  let book = empty_book();
  for (const line of lines.slice(1)) {
    book = add_contact(book, parse_csv_line(line));
  }
  return book;
}

/** One entry of the display list. */
export function display_line(c: Contact): string {
  return c.name + " — " + c.phone;
}

export function display_list(book: Book): string[] {
  return book.map(display_line);
}
