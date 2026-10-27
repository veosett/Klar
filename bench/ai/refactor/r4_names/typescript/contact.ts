/** A person in the contact book. `name` is the full name, e.g. "Ada Lovelace". */
export interface Contact {
  readonly name: string;
  readonly phone: string;
  readonly city: string;
}

const DIGITS = "0123456789";

function all_digits(s: string): boolean {
  return s.length > 0 && [...s].every((ch) => DIGITS.includes(ch));
}

/** Builds a contact. Throws an Error with the message of the first rule that fails. */
export function make_contact(name: string, phone: string, city: string): Contact {
  if (name === "") {
    throw new Error("name must not be empty");
  }
  if (!all_digits(phone)) {
    throw new Error("phone must be digits only");
  }
  return { name, phone, city };
}

/** The same contact with another phone number (validated like in `make_contact`). */
export function with_phone(c: Contact, phone: string): Contact {
  return make_contact(c.name, phone, c.city);
}

/** The same contact, moved to another city. */
export function with_city(c: Contact, city: string): Contact {
  return { ...c, city };
}
