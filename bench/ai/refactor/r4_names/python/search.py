from book import Book
from contact import Contact


def search_text(book: Book, text: str) -> list[Contact]:
    """Contacts whose name contains `text`, ignoring case."""
    needle = text.lower()
    return [c for c in book if needle in c.name.lower()]


def contacts_in_city(book: Book, city: str) -> list[Contact]:
    """Contacts living in `city`, ignoring case."""
    wanted = city.lower()
    return [c for c in book if c.city.lower() == wanted]


def find_by_phone(book: Book, phone: str) -> Contact | None:
    """The contact with this phone number, if any."""
    for c in book:
        if c.phone == phone:
            return c
    return None


def cities(book: Book) -> list[str]:
    """Every city in the book once, in alphabetical order."""
    return sorted({c.city for c in book})
