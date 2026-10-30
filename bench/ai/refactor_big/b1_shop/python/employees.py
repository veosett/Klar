from dataclasses import dataclass
from enum import Enum


class EmployeeKind(Enum):
    """The kinds of employee records."""
    PICKER = "Picker"
    DRIVER = "Driver"
    CLERK = "Clerk"


@dataclass(frozen=True)
class Employee:
    id: int
    name: str
    city: str
    kind: EmployeeKind
    shifts: int
    wage: float
    active: bool


def employees_find(xs: list[Employee], id: int) -> Employee | None:
    """The record with this id."""
    return next((x for x in xs if x.id == id), None)


def employees_in_city(xs: list[Employee], city: str) -> list[Employee]:
    """The records of one city."""
    return [x for x in xs if x.city == city]


def employees_active(xs: list[Employee]) -> list[Employee]:
    """The records in use."""
    return [x for x in xs if x.active]


def employees_names(xs: list[Employee]) -> list[str]:
    """The names, in order."""
    return sorted(x.name for x in xs)


def employees_total_shifts(xs: list[Employee]) -> int:
    """The sum of shifts."""
    return sum(x.shifts for x in xs)


def employees_total_wage(xs: list[Employee]) -> float:
    """The sum of wage."""
    return sum(x.wage for x in xs)


def employees_average_wage(xs: list[Employee]) -> float:
    """The mean of wage, 0 for no records."""
    if not xs:
        return 0.0
    return employees_total_wage(xs) / len(xs)


def employees_kind_label(k: EmployeeKind) -> str:
    """The kind as people read it."""
    return k.value


def employees_kind_weight(k: EmployeeKind) -> float:
    """How much a kind counts in a score."""
    match k:
        case EmployeeKind.PICKER:
            return 1.0
        case EmployeeKind.DRIVER:
            return 1.5
        case EmployeeKind.CLERK:
            return 2.0


def employees_describe(x: Employee) -> str:
    """One record as text."""
    return f"{x.name} ({x.city}), {employees_kind_label(x.kind)}: {x.shifts} shifts, {x.wage:.2f} wage"


def employees_by_kind(xs: list[Employee], k: EmployeeKind) -> list[Employee]:
    """The records of one kind."""
    return [x for x in xs if x.kind == k]


def employees_ranked(xs: list[Employee]) -> list[Employee]:
    """The records with the most shifts first."""
    return sorted(xs, key=lambda x: -x.shifts)


def employees_top(xs: list[Employee], n: int) -> list[Employee]:
    """The first few of the ranking."""
    return employees_ranked(xs)[:n]


def employees_validate(x: Employee) -> list[str]:
    """What is wrong with a record."""
    errors = []
    if not x.name:
        errors.append("no name")
    if not x.city:
        errors.append("no city")
    if x.shifts < 0:
        errors.append("negative shifts")
    if x.wage < 0.0:
        errors.append("negative wage")
    return errors


def employees_score(x: Employee) -> float:
    """The record with wage and shifts weighed together."""
    return x.wage * employees_kind_weight(x.kind) + x.shifts


def employees_row(x: Employee) -> str:
    """A row of the export file."""
    return f"{x.id},{x.name},{x.city},{employees_kind_label(x.kind)},{x.shifts},{x.wage:.2f}"


def employees_file(xs: list[Employee]) -> str:
    """The export file."""
    return "\n".join(["id,name,city,kind,shifts,wage", *(employees_row(x) for x in xs)])


def employees_per_city(xs: list[Employee]) -> dict[str, int]:
    """The number of records per city."""
    m: dict[str, int] = {}
    for x in xs:
        m[x.city] = m.get(x.city, 0) + 1
    return m


def employees_over(xs: list[Employee], limit: float) -> list[Employee]:
    """The records above a limit of wage."""
    return [x for x in xs if x.wage > limit]


def employees_summary(xs: list[Employee]) -> str:
    """A line for the dashboard."""
    return f"{len(xs)} employee records, {len(employees_active(xs))} active, {employees_total_wage(xs):.2f} wage"
