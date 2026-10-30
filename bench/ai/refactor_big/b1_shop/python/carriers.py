from dataclasses import dataclass
from enum import Enum


class CarrierKind(Enum):
    """The kinds of carrier records."""
    ROAD = "Road"
    RAIL = "Rail"
    COURIER = "Courier"


@dataclass(frozen=True)
class Carrier:
    id: int
    name: str
    city: str
    kind: CarrierKind
    vans: int
    fuel_cost: float
    active: bool


def carriers_find(xs: list[Carrier], id: int) -> Carrier | None:
    """The record with this id."""
    return next((x for x in xs if x.id == id), None)


def carriers_in_city(xs: list[Carrier], city: str) -> list[Carrier]:
    """The records of one city."""
    return [x for x in xs if x.city == city]


def carriers_active(xs: list[Carrier]) -> list[Carrier]:
    """The records in use."""
    return [x for x in xs if x.active]


def carriers_names(xs: list[Carrier]) -> list[str]:
    """The names, in order."""
    return sorted(x.name for x in xs)


def carriers_total_vans(xs: list[Carrier]) -> int:
    """The sum of vans."""
    return sum(x.vans for x in xs)


def carriers_total_fuel_cost(xs: list[Carrier]) -> float:
    """The sum of fuel_cost."""
    return sum(x.fuel_cost for x in xs)


def carriers_average_fuel_cost(xs: list[Carrier]) -> float:
    """The mean of fuel_cost, 0 for no records."""
    if not xs:
        return 0.0
    return carriers_total_fuel_cost(xs) / len(xs)


def carriers_kind_label(k: CarrierKind) -> str:
    """The kind as people read it."""
    return k.value


def carriers_kind_weight(k: CarrierKind) -> float:
    """How much a kind counts in a score."""
    match k:
        case CarrierKind.ROAD:
            return 1.0
        case CarrierKind.RAIL:
            return 1.5
        case CarrierKind.COURIER:
            return 2.0


def carriers_describe(x: Carrier) -> str:
    """One record as text."""
    return f"{x.name} ({x.city}), {carriers_kind_label(x.kind)}: {x.vans} vans, {x.fuel_cost:.2f} fuel_cost"


def carriers_by_kind(xs: list[Carrier], k: CarrierKind) -> list[Carrier]:
    """The records of one kind."""
    return [x for x in xs if x.kind == k]


def carriers_ranked(xs: list[Carrier]) -> list[Carrier]:
    """The records with the most vans first."""
    return sorted(xs, key=lambda x: -x.vans)


def carriers_top(xs: list[Carrier], n: int) -> list[Carrier]:
    """The first few of the ranking."""
    return carriers_ranked(xs)[:n]


def carriers_validate(x: Carrier) -> list[str]:
    """What is wrong with a record."""
    errors = []
    if not x.name:
        errors.append("no name")
    if not x.city:
        errors.append("no city")
    if x.vans < 0:
        errors.append("negative vans")
    if x.fuel_cost < 0.0:
        errors.append("negative fuel_cost")
    return errors


def carriers_score(x: Carrier) -> float:
    """The record with fuel_cost and vans weighed together."""
    return x.fuel_cost * carriers_kind_weight(x.kind) + x.vans


def carriers_row(x: Carrier) -> str:
    """A row of the export file."""
    return f"{x.id},{x.name},{x.city},{carriers_kind_label(x.kind)},{x.vans},{x.fuel_cost:.2f}"


def carriers_file(xs: list[Carrier]) -> str:
    """The export file."""
    return "\n".join(["id,name,city,kind,vans,fuel_cost", *(carriers_row(x) for x in xs)])


def carriers_per_city(xs: list[Carrier]) -> dict[str, int]:
    """The number of records per city."""
    m: dict[str, int] = {}
    for x in xs:
        m[x.city] = m.get(x.city, 0) + 1
    return m


def carriers_over(xs: list[Carrier], limit: float) -> list[Carrier]:
    """The records above a limit of fuel_cost."""
    return [x for x in xs if x.fuel_cost > limit]


def carriers_summary(xs: list[Carrier]) -> str:
    """A line for the dashboard."""
    return f"{len(xs)} carrier records, {len(carriers_active(xs))} active, {carriers_total_fuel_cost(xs):.2f} fuel_cost"
