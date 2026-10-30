from dataclasses import dataclass
from enum import Enum


class SupplierKind(Enum):
    """The kinds of supplier records."""
    MAKER = "Maker"
    RESELLER = "Reseller"
    IMPORTER = "Importer"


@dataclass(frozen=True)
class Supplier:
    id: int
    name: str
    city: str
    kind: SupplierKind
    lead_days: int
    rating: float
    active: bool


def suppliers_find(xs: list[Supplier], id: int) -> Supplier | None:
    """The record with this id."""
    return next((x for x in xs if x.id == id), None)


def suppliers_in_city(xs: list[Supplier], city: str) -> list[Supplier]:
    """The records of one city."""
    return [x for x in xs if x.city == city]


def suppliers_active(xs: list[Supplier]) -> list[Supplier]:
    """The records in use."""
    return [x for x in xs if x.active]


def suppliers_names(xs: list[Supplier]) -> list[str]:
    """The names, in order."""
    return sorted(x.name for x in xs)


def suppliers_total_lead_days(xs: list[Supplier]) -> int:
    """The sum of lead_days."""
    return sum(x.lead_days for x in xs)


def suppliers_total_rating(xs: list[Supplier]) -> float:
    """The sum of rating."""
    return sum(x.rating for x in xs)


def suppliers_average_rating(xs: list[Supplier]) -> float:
    """The mean of rating, 0 for no records."""
    if not xs:
        return 0.0
    return suppliers_total_rating(xs) / len(xs)


def suppliers_kind_label(k: SupplierKind) -> str:
    """The kind as people read it."""
    return k.value


def suppliers_kind_weight(k: SupplierKind) -> float:
    """How much a kind counts in a score."""
    match k:
        case SupplierKind.MAKER:
            return 1.0
        case SupplierKind.RESELLER:
            return 1.5
        case SupplierKind.IMPORTER:
            return 2.0


def suppliers_describe(x: Supplier) -> str:
    """One record as text."""
    return f"{x.name} ({x.city}), {suppliers_kind_label(x.kind)}: {x.lead_days} lead_days, {x.rating:.2f} rating"


def suppliers_by_kind(xs: list[Supplier], k: SupplierKind) -> list[Supplier]:
    """The records of one kind."""
    return [x for x in xs if x.kind == k]


def suppliers_ranked(xs: list[Supplier]) -> list[Supplier]:
    """The records with the most lead_days first."""
    return sorted(xs, key=lambda x: -x.lead_days)


def suppliers_top(xs: list[Supplier], n: int) -> list[Supplier]:
    """The first few of the ranking."""
    return suppliers_ranked(xs)[:n]


def suppliers_validate(x: Supplier) -> list[str]:
    """What is wrong with a record."""
    errors = []
    if not x.name:
        errors.append("no name")
    if not x.city:
        errors.append("no city")
    if x.lead_days < 0:
        errors.append("negative lead_days")
    if x.rating < 0.0:
        errors.append("negative rating")
    return errors


def suppliers_score(x: Supplier) -> float:
    """The record with rating and lead_days weighed together."""
    return x.rating * suppliers_kind_weight(x.kind) + x.lead_days


def suppliers_row(x: Supplier) -> str:
    """A row of the export file."""
    return f"{x.id},{x.name},{x.city},{suppliers_kind_label(x.kind)},{x.lead_days},{x.rating:.2f}"


def suppliers_file(xs: list[Supplier]) -> str:
    """The export file."""
    return "\n".join(["id,name,city,kind,lead_days,rating", *(suppliers_row(x) for x in xs)])


def suppliers_per_city(xs: list[Supplier]) -> dict[str, int]:
    """The number of records per city."""
    m: dict[str, int] = {}
    for x in xs:
        m[x.city] = m.get(x.city, 0) + 1
    return m


def suppliers_over(xs: list[Supplier], limit: float) -> list[Supplier]:
    """The records above a limit of rating."""
    return [x for x in xs if x.rating > limit]


def suppliers_summary(xs: list[Supplier]) -> str:
    """A line for the dashboard."""
    return f"{len(xs)} supplier records, {len(suppliers_active(xs))} active, {suppliers_total_rating(xs):.2f} rating"
