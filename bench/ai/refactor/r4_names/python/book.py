from contact import Contact, with_phone

# The contacts in the order they were added (until `sort_book`).
Book = list[Contact]


def empty_book() -> Book:
    return []


def count_contacts(book: Book) -> int:
    return len(book)


def find_contact(book: Book, name: str) -> Contact | None:
    """The contact with exactly this name, if there is one."""
    for c in book:
        if c.name == name:
            return c
    return None


def add_contact(book: Book, c: Contact) -> Book:
    """Adds a contact; a second contact with the same name is refused (ValueError)."""
    if find_contact(book, c.name) is not None:
        raise ValueError("duplicate contact: " + c.name)
    return book + [c]


def remove_contact(book: Book, name: str) -> Book:
    """Removes the contact with this name; the book is unchanged if there is none."""
    return [c for c in book if c.name != name]


def update_phone(book: Book, name: str, phone: str) -> Book:
    """Gives the contact with this name a new phone number."""
    found = find_contact(book, name)
    if found is None:
        raise ValueError("no such contact: " + name)
    updated = with_phone(found, phone)
    return [updated if c.name == name else c for c in book]


def sort_book(book: Book) -> Book:
    """The book ordered by name, ignoring case."""
    return sorted(book, key=lambda c: c.name.lower())
