from model import Customer, Tier


def display_name(c: Customer) -> str:
    """The customer's name as people read it."""
    return f"{c.first_name} {c.last_name}"


def sorted_customers(cs: list[Customer]) -> list[Customer]:
    """Customers in alphabetical order."""
    return sorted(cs, key=lambda c: (c.last_name, c.first_name))


def find_by_name(cs: list[Customer], text: str) -> list[Customer]:
    """Customers whose name contains the text, in any case."""
    q = text.lower()
    return [c for c in cs if q in c.first_name.lower() or q in c.last_name.lower()]


def initials(c: Customer) -> str:
    """The initials of a customer: "AL" for "Ada Lovelace"."""
    return (c.first_name[:1] + c.last_name[:1]).upper()


def greeting(c: Customer) -> str:
    """The opening of a letter."""
    return f"Dear {c.first_name} {c.last_name}"


def mailing_line(c: Customer) -> str:
    """An address line."""
    return f"{c.first_name} {c.last_name} <{c.email}>"


TIERS = {"gold": Tier.GOLD, "silver": Tier.SILVER}


def tier_text(t: Tier) -> str:
    return t.value


def parse_customer(row: str) -> Customer | None:
    """A customer from a row of the customer file."""
    cells = row.split(",")
    if len(cells) != 6 or not cells[0].isdigit():
        return None
    return Customer(int(cells[0]), cells[1], cells[2], cells[3], TIERS.get(cells[4], Tier.BASIC), cells[5])


def customer_header() -> str:
    """The first row of the customer file."""
    return "id,first_name,last_name,email,tier,city"


def customer_row(c: Customer) -> str:
    """A row of the customer file."""
    return f"{c.id},{c.first_name},{c.last_name},{c.email},{tier_text(c.tier)},{c.city}"


def validate_customer(c: Customer) -> list[str]:
    """What is wrong with a customer."""
    errors = []
    if not c.first_name:
        errors.append("first name is empty")
    if not c.last_name:
        errors.append("last name is empty")
    if "@" not in c.email:
        errors.append("bad email")
    return errors


def same_person(a: Customer, b: Customer) -> bool:
    """True for two records of the same person."""
    return a.first_name.lower() == b.first_name.lower() and a.last_name.lower() == b.last_name.lower() and a.email == b.email
