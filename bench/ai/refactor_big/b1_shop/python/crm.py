from model import Customer, Tier


def display_name(c: Customer) -> str:
    """The customer's name as people read it."""
    return c.name


def sorted_customers(cs: list[Customer]) -> list[Customer]:
    """Customers in alphabetical order."""
    return sorted(cs, key=lambda c: c.name)


def find_by_name(cs: list[Customer], text: str) -> list[Customer]:
    """Customers whose name contains the text, in any case."""
    q = text.lower()
    return [c for c in cs if q in c.name.lower()]


def initials(c: Customer) -> str:
    """The initials of a customer: "AL" for "Ada Lovelace"."""
    return "".join(w[:1].upper() for w in c.name.split(" "))


def greeting(c: Customer) -> str:
    """The opening of a letter."""
    return f"Dear {c.name}"


def mailing_line(c: Customer) -> str:
    """An address line."""
    return f"{c.name} <{c.email}>"


TIERS = {"gold": Tier.GOLD, "silver": Tier.SILVER}


def tier_text(t: Tier) -> str:
    return t.value


def parse_customer(row: str) -> Customer | None:
    """A customer from a row of the customer file."""
    cells = row.split(",")
    if len(cells) != 5 or not cells[0].isdigit():
        return None
    return Customer(int(cells[0]), cells[1], cells[2], TIERS.get(cells[3], Tier.BASIC), cells[4])


def customer_header() -> str:
    """The first row of the customer file."""
    return "id,name,email,tier,city"


def customer_row(c: Customer) -> str:
    """A row of the customer file."""
    return f"{c.id},{c.name},{c.email},{tier_text(c.tier)},{c.city}"


def validate_customer(c: Customer) -> list[str]:
    """What is wrong with a customer."""
    errors = []
    if not c.name:
        errors.append("name is empty")
    if "@" not in c.email:
        errors.append("bad email")
    return errors


def same_person(a: Customer, b: Customer) -> bool:
    """True for two records of the same person."""
    return a.name.lower() == b.name.lower() and a.email == b.email
