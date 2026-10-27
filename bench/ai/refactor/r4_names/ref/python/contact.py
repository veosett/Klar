from dataclasses import dataclass, replace

DIGITS = "0123456789"


@dataclass(frozen=True)
class Contact:
    """A person in the contact book."""

    first: str
    last: str
    phone: str
    city: str


def all_digits(s: str) -> bool:
    return len(s) > 0 and all(ch in DIGITS for ch in s)


def make_contact(first: str, last: str, phone: str, city: str) -> Contact:
    """Builds a contact. Raises ValueError with the message of the first rule that fails."""
    if first == "":
        raise ValueError("first name must not be empty")
    if last == "":
        raise ValueError("last name must not be empty")
    if not all_digits(phone):
        raise ValueError("phone must be digits only")
    return Contact(first=first, last=last, phone=phone, city=city)


def with_phone(c: Contact, phone: str) -> Contact:
    """The same contact with another phone number (validated like in `make_contact`)."""
    return make_contact(first=c.first, last=c.last, phone=phone, city=c.city)


def with_city(c: Contact, city: str) -> Contact:
    """The same contact, moved to another city."""
    return replace(c, city=city)


def initials(c: Contact) -> str:
    """The upper-case initials, e.g. "A.L." for Ada Lovelace."""
    return c.first[0].upper() + "." + c.last[0].upper() + "."
