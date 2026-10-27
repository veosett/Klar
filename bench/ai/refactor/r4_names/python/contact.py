from dataclasses import dataclass, replace

DIGITS = "0123456789"


@dataclass(frozen=True)
class Contact:
    """A person in the contact book. `name` is the full name, e.g. "Ada Lovelace"."""

    name: str
    phone: str
    city: str


def all_digits(s: str) -> bool:
    return len(s) > 0 and all(ch in DIGITS for ch in s)


def make_contact(name: str, phone: str, city: str) -> Contact:
    """Builds a contact. Raises ValueError with the message of the first rule that fails."""
    if name == "":
        raise ValueError("name must not be empty")
    if not all_digits(phone):
        raise ValueError("phone must be digits only")
    return Contact(name=name, phone=phone, city=city)


def with_phone(c: Contact, phone: str) -> Contact:
    """The same contact with another phone number (validated like in `make_contact`)."""
    return make_contact(name=c.name, phone=phone, city=c.city)


def with_city(c: Contact, city: str) -> Contact:
    """The same contact, moved to another city."""
    return replace(c, city=city)
