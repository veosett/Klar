from contact import Contact, with_phone

# The contacts in the order they were added (until `sort_book`).
Book = list[Contact]


def empty_book() -> Book:
    return []


def count_contacts(book: Book) -> int:
    return len(book)


def find_contact(book: Book, first: str, last: str) -> Contact | None:
    """The contact with exactly this first and last name, if there is one."""
    for c in book:
        if c.first == first and c.last == last:
            return c
    return None


def add_contact(book: Book, c: Contact) -> Book:
    """Adds a contact; a second contact with the same first and last name is refused (ValueError)."""
    if find_contact(book, c.first, c.last) is not None:
        raise ValueError("duplicate contact: " + c.first + " " + c.last)
    return book + [c]


def remove_contact(book: Book, first: str, last: str) -> Book:
    """Removes the contact with this name; the book is unchanged if there is none."""
    return [c for c in book if c.first != first or c.last != last]


def update_phone(book: Book, first: str, last: str, phone: str) -> Book:
    """Gives the contact with this name a new phone number."""
    found = find_contact(book, first, last)
    if found is None:
        raise ValueError("no such contact: " + first + " " + last)
    updated = with_phone(found, phone)
    return [updated if c.first == first and c.last == last else c for c in book]


def sort_book(book: Book) -> Book:
    """The book ordered by last name, then first name, ignoring case."""
    return sorted(book, key=lambda c: (c.last.lower(), c.first.lower()))
