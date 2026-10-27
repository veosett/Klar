from book import Book, add_contact, empty_book
from contact import Contact, make_contact

CSV_HEADER = "last,first,phone,city"


def csv_line(c: Contact) -> str:
    """One CSV line; no quoting or escaping."""
    return c.last + "," + c.first + "," + c.phone + "," + c.city


def csv_lines(book: Book) -> list[str]:
    """The header line followed by one line per contact, in book order."""
    return [CSV_HEADER] + [csv_line(c) for c in book]


def csv_text(book: Book) -> str:
    """The whole CSV file as one text, one line per row."""
    return "\n".join(csv_lines(book)) + "\n"


def parse_csv_line(line: str) -> Contact:
    """Reads one CSV line (as written by `csv_line`) back into a contact."""
    fields = line.split(",")
    if len(fields) != 4:
        raise ValueError("bad csv line: " + line)
    return make_contact(first=fields[1], last=fields[0], phone=fields[2], city=fields[3])


def read_csv(lines: list[str]) -> Book:
    """Reads the output of `csv_lines` back into a book; stops at the first bad line."""
    if len(lines) == 0 or lines[0] != CSV_HEADER:
        raise ValueError("bad csv header")
    book = empty_book()
    for line in lines[1:]:
        book = add_contact(book, parse_csv_line(line))
    return book


def display_line(c: Contact) -> str:
    """One entry of the display list."""
    return c.last + ", " + c.first + " — " + c.phone


def display_list(book: Book) -> list[str]:
    return [display_line(c) for c in book]
