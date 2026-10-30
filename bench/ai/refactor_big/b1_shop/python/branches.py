from dataclasses import dataclass
from enum import Enum


class BranchKind(Enum):
    """The kinds of branch records."""
    SHOP = "Shop"
    OFFICE = "Office"
    DEPOT = "Depot"


@dataclass(frozen=True)
class Branch:
    id: int
    name: str
    city: str
    kind: BranchKind
    desks: int
    floor_area: float
    active: bool


def branches_find(xs: list[Branch], id: int) -> Branch | None:
    """The record with this id."""
    return next((x for x in xs if x.id == id), None)


def branches_in_city(xs: list[Branch], city: str) -> list[Branch]:
    """The records of one city."""
    return [x for x in xs if x.city == city]


def branches_active(xs: list[Branch]) -> list[Branch]:
    """The records in use."""
    return [x for x in xs if x.active]


def branches_names(xs: list[Branch]) -> list[str]:
    """The names, in order."""
    return sorted(x.name for x in xs)


def branches_total_desks(xs: list[Branch]) -> int:
    """The sum of desks."""
    return sum(x.desks for x in xs)


def branches_total_floor_area(xs: list[Branch]) -> float:
    """The sum of floor_area."""
    return sum(x.floor_area for x in xs)


def branches_average_floor_area(xs: list[Branch]) -> float:
    """The mean of floor_area, 0 for no records."""
    if not xs:
        return 0.0
    return branches_total_floor_area(xs) / len(xs)


def branches_kind_label(k: BranchKind) -> str:
    """The kind as people read it."""
    return k.value


def branches_kind_weight(k: BranchKind) -> float:
    """How much a kind counts in a score."""
    match k:
        case BranchKind.SHOP:
            return 1.0
        case BranchKind.OFFICE:
            return 1.5
        case BranchKind.DEPOT:
            return 2.0


def branches_describe(x: Branch) -> str:
    """One record as text."""
    return f"{x.name} ({x.city}), {branches_kind_label(x.kind)}: {x.desks} desks, {x.floor_area:.2f} floor_area"


def branches_by_kind(xs: list[Branch], k: BranchKind) -> list[Branch]:
    """The records of one kind."""
    return [x for x in xs if x.kind == k]


def branches_ranked(xs: list[Branch]) -> list[Branch]:
    """The records with the most desks first."""
    return sorted(xs, key=lambda x: -x.desks)


def branches_top(xs: list[Branch], n: int) -> list[Branch]:
    """The first few of the ranking."""
    return branches_ranked(xs)[:n]


def branches_validate(x: Branch) -> list[str]:
    """What is wrong with a record."""
    errors = []
    if not x.name:
        errors.append("no name")
    if not x.city:
        errors.append("no city")
    if x.desks < 0:
        errors.append("negative desks")
    if x.floor_area < 0.0:
        errors.append("negative floor_area")
    return errors


def branches_score(x: Branch) -> float:
    """The record with floor_area and desks weighed together."""
    return x.floor_area * branches_kind_weight(x.kind) + x.desks


def branches_row(x: Branch) -> str:
    """A row of the export file."""
    return f"{x.id},{x.name},{x.city},{branches_kind_label(x.kind)},{x.desks},{x.floor_area:.2f}"


def branches_file(xs: list[Branch]) -> str:
    """The export file."""
    return "\n".join(["id,name,city,kind,desks,floor_area", *(branches_row(x) for x in xs)])


def branches_per_city(xs: list[Branch]) -> dict[str, int]:
    """The number of records per city."""
    m: dict[str, int] = {}
    for x in xs:
        m[x.city] = m.get(x.city, 0) + 1
    return m


def branches_over(xs: list[Branch], limit: float) -> list[Branch]:
    """The records above a limit of floor_area."""
    return [x for x in xs if x.floor_area > limit]


def branches_summary(xs: list[Branch]) -> str:
    """A line for the dashboard."""
    return f"{len(xs)} branch records, {len(branches_active(xs))} active, {branches_total_floor_area(xs):.2f} floor_area"
