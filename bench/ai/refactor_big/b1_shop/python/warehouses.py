from dataclasses import dataclass
from enum import Enum


class WarehouseKind(Enum):
    """The kinds of warehouse records."""
    CENTRAL = "Central"
    REGIONAL = "Regional"
    OVERFLOW = "Overflow"


@dataclass(frozen=True)
class Warehouse:
    id: int
    name: str
    city: str
    kind: WarehouseKind
    bays: int
    rent: float
    active: bool


def warehouses_find(xs: list[Warehouse], id: int) -> Warehouse | None:
    """The record with this id."""
    return next((x for x in xs if x.id == id), None)


def warehouses_in_city(xs: list[Warehouse], city: str) -> list[Warehouse]:
    """The records of one city."""
    return [x for x in xs if x.city == city]


def warehouses_active(xs: list[Warehouse]) -> list[Warehouse]:
    """The records in use."""
    return [x for x in xs if x.active]


def warehouses_names(xs: list[Warehouse]) -> list[str]:
    """The names, in order."""
    return sorted(x.name for x in xs)


def warehouses_total_bays(xs: list[Warehouse]) -> int:
    """The sum of bays."""
    return sum(x.bays for x in xs)


def warehouses_total_rent(xs: list[Warehouse]) -> float:
    """The sum of rent."""
    return sum(x.rent for x in xs)


def warehouses_average_rent(xs: list[Warehouse]) -> float:
    """The mean of rent, 0 for no records."""
    if not xs:
        return 0.0
    return warehouses_total_rent(xs) / len(xs)


def warehouses_kind_label(k: WarehouseKind) -> str:
    """The kind as people read it."""
    return k.value


def warehouses_kind_weight(k: WarehouseKind) -> float:
    """How much a kind counts in a score."""
    match k:
        case WarehouseKind.CENTRAL:
            return 1.0
        case WarehouseKind.REGIONAL:
            return 1.5
        case WarehouseKind.OVERFLOW:
            return 2.0


def warehouses_describe(x: Warehouse) -> str:
    """One record as text."""
    return f"{x.name} ({x.city}), {warehouses_kind_label(x.kind)}: {x.bays} bays, {x.rent:.2f} rent"


def warehouses_by_kind(xs: list[Warehouse], k: WarehouseKind) -> list[Warehouse]:
    """The records of one kind."""
    return [x for x in xs if x.kind == k]


def warehouses_ranked(xs: list[Warehouse]) -> list[Warehouse]:
    """The records with the most bays first."""
    return sorted(xs, key=lambda x: -x.bays)


def warehouses_top(xs: list[Warehouse], n: int) -> list[Warehouse]:
    """The first few of the ranking."""
    return warehouses_ranked(xs)[:n]


def warehouses_validate(x: Warehouse) -> list[str]:
    """What is wrong with a record."""
    errors = []
    if not x.name:
        errors.append("no name")
    if not x.city:
        errors.append("no city")
    if x.bays < 0:
        errors.append("negative bays")
    if x.rent < 0.0:
        errors.append("negative rent")
    return errors


def warehouses_score(x: Warehouse) -> float:
    """The record with rent and bays weighed together."""
    return x.rent * warehouses_kind_weight(x.kind) + x.bays


def warehouses_row(x: Warehouse) -> str:
    """A row of the export file."""
    return f"{x.id},{x.name},{x.city},{warehouses_kind_label(x.kind)},{x.bays},{x.rent:.2f}"


def warehouses_file(xs: list[Warehouse]) -> str:
    """The export file."""
    return "\n".join(["id,name,city,kind,bays,rent", *(warehouses_row(x) for x in xs)])


def warehouses_per_city(xs: list[Warehouse]) -> dict[str, int]:
    """The number of records per city."""
    m: dict[str, int] = {}
    for x in xs:
        m[x.city] = m.get(x.city, 0) + 1
    return m


def warehouses_over(xs: list[Warehouse], limit: float) -> list[Warehouse]:
    """The records above a limit of rent."""
    return [x for x in xs if x.rent > limit]


def warehouses_summary(xs: list[Warehouse]) -> str:
    """A line for the dashboard."""
    return f"{len(xs)} warehouse records, {len(warehouses_active(xs))} active, {warehouses_total_rent(xs):.2f} rent"
