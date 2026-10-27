/** A person in the contact book. */
export interface Contact {
  readonly first: string;
  readonly last: string;
  readonly phone: string;
  readonly city: string;
}

const DIGITS = "0123456789";

function all_digits(s: string): boolean {
  return s.length > 0 && [...s].every((ch) => DIGITS.includes(ch));
}

/** Builds a contact. Throws an Error with the message of the first rule that fails. */
export function make_contact(first: string, last: string, phone: string, city: string): Contact {
  if (first === "") {
    throw new Error("first name must not be empty");
  }
  if (last === "") {
    throw new Error("last name must not be empty");
  }
  if (!all_digits(phone)) {
    throw new Error("phone must be digits only");
  }
  return { first, last, phone, city };
}

/** The same contact with another phone number (validated like in `make_contact`). */
export function with_phone(c: Contact, phone: string): Contact {
  return make_contact(c.first, c.last, phone, c.city);
}

/** The same contact, moved to another city. */
export function with_city(c: Contact, city: string): Contact {
  return { ...c, city };
}

/** The upper-case initials, e.g. "A.L." for Ada Lovelace. */
export function initials(c: Contact): string {
  return c.first.charAt(0).toUpperCase() + "." + c.last.charAt(0).toUpperCase() + ".";
}
