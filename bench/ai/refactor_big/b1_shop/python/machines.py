from dataclasses import dataclass
from enum import Enum


class MachineKind(Enum):
    """The kinds of machine records."""
    PRESS = "Press"
    SCANNER = "Scanner"
    LIFT = "Lift"


@dataclass(frozen=True)
class Machine:
    id: int
    name: str
    city: str
    kind: MachineKind
    cycles: int
    power: float
    active: bool


def machines_find(xs: list[Machine], id: int) -> Machine | None:
    """The record with this id."""
    return next((x for x in xs if x.id == id), None)


def machines_in_city(xs: list[Machine], city: str) -> list[Machine]:
    """The records of one city."""
    return [x for x in xs if x.city == city]


def machines_active(xs: list[Machine]) -> list[Machine]:
    """The records in use."""
    return [x for x in xs if x.active]


def machines_names(xs: list[Machine]) -> list[str]:
    """The names, in order."""
    return sorted(x.name for x in xs)


def machines_total_cycles(xs: list[Machine]) -> int:
    """The sum of cycles."""
    return sum(x.cycles for x in xs)


def machines_total_power(xs: list[Machine]) -> float:
    """The sum of power."""
    return sum(x.power for x in xs)


def machines_average_power(xs: list[Machine]) -> float:
    """The mean of power, 0 for no records."""
    if not xs:
        return 0.0
    return machines_total_power(xs) / len(xs)


def machines_kind_label(k: MachineKind) -> str:
    """The kind as people read it."""
    return k.value


def machines_kind_weight(k: MachineKind) -> float:
    """How much a kind counts in a score."""
    match k:
        case MachineKind.PRESS:
            return 1.0
        case MachineKind.SCANNER:
            return 1.5
        case MachineKind.LIFT:
            return 2.0


def machines_describe(x: Machine) -> str:
    """One record as text."""
    return f"{x.name} ({x.city}), {machines_kind_label(x.kind)}: {x.cycles} cycles, {x.power:.2f} power"


def machines_by_kind(xs: list[Machine], k: MachineKind) -> list[Machine]:
    """The records of one kind."""
    return [x for x in xs if x.kind == k]


def machines_ranked(xs: list[Machine]) -> list[Machine]:
    """The records with the most cycles first."""
    return sorted(xs, key=lambda x: -x.cycles)


def machines_top(xs: list[Machine], n: int) -> list[Machine]:
    """The first few of the ranking."""
    return machines_ranked(xs)[:n]


def machines_validate(x: Machine) -> list[str]:
    """What is wrong with a record."""
    errors = []
    if not x.name:
        errors.append("no name")
    if not x.city:
        errors.append("no city")
    if x.cycles < 0:
        errors.append("negative cycles")
    if x.power < 0.0:
        errors.append("negative power")
    return errors


def machines_score(x: Machine) -> float:
    """The record with power and cycles weighed together."""
    return x.power * machines_kind_weight(x.kind) + x.cycles


def machines_row(x: Machine) -> str:
    """A row of the export file."""
    return f"{x.id},{x.name},{x.city},{machines_kind_label(x.kind)},{x.cycles},{x.power:.2f}"


def machines_file(xs: list[Machine]) -> str:
    """The export file."""
    return "\n".join(["id,name,city,kind,cycles,power", *(machines_row(x) for x in xs)])


def machines_per_city(xs: list[Machine]) -> dict[str, int]:
    """The number of records per city."""
    m: dict[str, int] = {}
    for x in xs:
        m[x.city] = m.get(x.city, 0) + 1
    return m


def machines_over(xs: list[Machine], limit: float) -> list[Machine]:
    """The records above a limit of power."""
    return [x for x in xs if x.power > limit]


def machines_summary(xs: list[Machine]) -> str:
    """A line for the dashboard."""
    return f"{len(xs)} machine records, {len(machines_active(xs))} active, {machines_total_power(xs):.2f} power"
