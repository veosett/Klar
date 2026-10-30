from dataclasses import dataclass
from enum import Enum


class AssetKind(Enum):
    """The kinds of asset records."""
    VEHICLE = "Vehicle"
    FIXTURE = "Fixture"
    DEVICE = "Device"


@dataclass(frozen=True)
class Asset:
    id: int
    name: str
    city: str
    kind: AssetKind
    age_years: int
    book_value: float
    active: bool


def assets_find(xs: list[Asset], id: int) -> Asset | None:
    """The record with this id."""
    return next((x for x in xs if x.id == id), None)


def assets_in_city(xs: list[Asset], city: str) -> list[Asset]:
    """The records of one city."""
    return [x for x in xs if x.city == city]


def assets_active(xs: list[Asset]) -> list[Asset]:
    """The records in use."""
    return [x for x in xs if x.active]


def assets_names(xs: list[Asset]) -> list[str]:
    """The names, in order."""
    return sorted(x.name for x in xs)


def assets_total_age_years(xs: list[Asset]) -> int:
    """The sum of age_years."""
    return sum(x.age_years for x in xs)


def assets_total_book_value(xs: list[Asset]) -> float:
    """The sum of book_value."""
    return sum(x.book_value for x in xs)


def assets_average_book_value(xs: list[Asset]) -> float:
    """The mean of book_value, 0 for no records."""
    if not xs:
        return 0.0
    return assets_total_book_value(xs) / len(xs)


def assets_kind_label(k: AssetKind) -> str:
    """The kind as people read it."""
    return k.value


def assets_kind_weight(k: AssetKind) -> float:
    """How much a kind counts in a score."""
    match k:
        case AssetKind.VEHICLE:
            return 1.0
        case AssetKind.FIXTURE:
            return 1.5
        case AssetKind.DEVICE:
            return 2.0


def assets_describe(x: Asset) -> str:
    """One record as text."""
    return f"{x.name} ({x.city}), {assets_kind_label(x.kind)}: {x.age_years} age_years, {x.book_value:.2f} book_value"


def assets_by_kind(xs: list[Asset], k: AssetKind) -> list[Asset]:
    """The records of one kind."""
    return [x for x in xs if x.kind == k]


def assets_ranked(xs: list[Asset]) -> list[Asset]:
    """The records with the most age_years first."""
    return sorted(xs, key=lambda x: -x.age_years)


def assets_top(xs: list[Asset], n: int) -> list[Asset]:
    """The first few of the ranking."""
    return assets_ranked(xs)[:n]


def assets_validate(x: Asset) -> list[str]:
    """What is wrong with a record."""
    errors = []
    if not x.name:
        errors.append("no name")
    if not x.city:
        errors.append("no city")
    if x.age_years < 0:
        errors.append("negative age_years")
    if x.book_value < 0.0:
        errors.append("negative book_value")
    return errors


def assets_score(x: Asset) -> float:
    """The record with book_value and age_years weighed together."""
    return x.book_value * assets_kind_weight(x.kind) + x.age_years


def assets_row(x: Asset) -> str:
    """A row of the export file."""
    return f"{x.id},{x.name},{x.city},{assets_kind_label(x.kind)},{x.age_years},{x.book_value:.2f}"


def assets_file(xs: list[Asset]) -> str:
    """The export file."""
    return "\n".join(["id,name,city,kind,age_years,book_value", *(assets_row(x) for x in xs)])


def assets_per_city(xs: list[Asset]) -> dict[str, int]:
    """The number of records per city."""
    m: dict[str, int] = {}
    for x in xs:
        m[x.city] = m.get(x.city, 0) + 1
    return m


def assets_over(xs: list[Asset], limit: float) -> list[Asset]:
    """The records above a limit of book_value."""
    return [x for x in xs if x.book_value > limit]


def assets_summary(xs: list[Asset]) -> str:
    """A line for the dashboard."""
    return f"{len(xs)} asset records, {len(assets_active(xs))} active, {assets_total_book_value(xs):.2f} book_value"
