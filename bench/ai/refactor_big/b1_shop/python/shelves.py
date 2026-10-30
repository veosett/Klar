from dataclasses import dataclass
from enum import Enum


class ShelfKind(Enum):
    """The kinds of shelf records."""
    OPEN = "Open"
    COLD = "Cold"
    LOCKED = "Locked"


@dataclass(frozen=True)
class Shelf:
    id: int
    name: str
    city: str
    kind: ShelfKind
    slots: int
    height: float
    active: bool


def shelves_find(xs: list[Shelf], id: int) -> Shelf | None:
    """The record with this id."""
    return next((x for x in xs if x.id == id), None)


def shelves_in_city(xs: list[Shelf], city: str) -> list[Shelf]:
    """The records of one city."""
    return [x for x in xs if x.city == city]


def shelves_active(xs: list[Shelf]) -> list[Shelf]:
    """The records in use."""
    return [x for x in xs if x.active]


def shelves_names(xs: list[Shelf]) -> list[str]:
    """The names, in order."""
    return sorted(x.name for x in xs)


def shelves_total_slots(xs: list[Shelf]) -> int:
    """The sum of slots."""
    return sum(x.slots for x in xs)


def shelves_total_height(xs: list[Shelf]) -> float:
    """The sum of height."""
    return sum(x.height for x in xs)


def shelves_average_height(xs: list[Shelf]) -> float:
    """The mean of height, 0 for no records."""
    if not xs:
        return 0.0
    return shelves_total_height(xs) / len(xs)


def shelves_kind_label(k: ShelfKind) -> str:
    """The kind as people read it."""
    return k.value


def shelves_kind_weight(k: ShelfKind) -> float:
    """How much a kind counts in a score."""
    match k:
        case ShelfKind.OPEN:
            return 1.0
        case ShelfKind.COLD:
            return 1.5
        case ShelfKind.LOCKED:
            return 2.0


def shelves_describe(x: Shelf) -> str:
    """One record as text."""
    return f"{x.name} ({x.city}), {shelves_kind_label(x.kind)}: {x.slots} slots, {x.height:.2f} height"


def shelves_by_kind(xs: list[Shelf], k: ShelfKind) -> list[Shelf]:
    """The records of one kind."""
    return [x for x in xs if x.kind == k]


def shelves_ranked(xs: list[Shelf]) -> list[Shelf]:
    """The records with the most slots first."""
    return sorted(xs, key=lambda x: -x.slots)


def shelves_top(xs: list[Shelf], n: int) -> list[Shelf]:
    """The first few of the ranking."""
    return shelves_ranked(xs)[:n]


def shelves_validate(x: Shelf) -> list[str]:
    """What is wrong with a record."""
    errors = []
    if not x.name:
        errors.append("no name")
    if not x.city:
        errors.append("no city")
    if x.slots < 0:
        errors.append("negative slots")
    if x.height < 0.0:
        errors.append("negative height")
    return errors


def shelves_score(x: Shelf) -> float:
    """The record with height and slots weighed together."""
    return x.height * shelves_kind_weight(x.kind) + x.slots


def shelves_row(x: Shelf) -> str:
    """A row of the export file."""
    return f"{x.id},{x.name},{x.city},{shelves_kind_label(x.kind)},{x.slots},{x.height:.2f}"


def shelves_file(xs: list[Shelf]) -> str:
    """The export file."""
    return "\n".join(["id,name,city,kind,slots,height", *(shelves_row(x) for x in xs)])


def shelves_per_city(xs: list[Shelf]) -> dict[str, int]:
    """The number of records per city."""
    m: dict[str, int] = {}
    for x in xs:
        m[x.city] = m.get(x.city, 0) + 1
    return m


def shelves_over(xs: list[Shelf], limit: float) -> list[Shelf]:
    """The records above a limit of height."""
    return [x for x in xs if x.height > limit]


def shelves_summary(xs: list[Shelf]) -> str:
    """A line for the dashboard."""
    return f"{len(xs)} shelf records, {len(shelves_active(xs))} active, {shelves_total_height(xs):.2f} height"
