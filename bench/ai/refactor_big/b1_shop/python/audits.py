from dataclasses import dataclass
from enum import Enum


class InspectionKind(Enum):
    """The kinds of inspection records."""
    SAFETY = "Safety"
    STOCK = "Stock"
    TAX = "Tax"


@dataclass(frozen=True)
class Inspection:
    id: int
    name: str
    city: str
    kind: InspectionKind
    findings: int
    duration: float
    active: bool


def audits_find(xs: list[Inspection], id: int) -> Inspection | None:
    """The record with this id."""
    return next((x for x in xs if x.id == id), None)


def audits_in_city(xs: list[Inspection], city: str) -> list[Inspection]:
    """The records of one city."""
    return [x for x in xs if x.city == city]


def audits_active(xs: list[Inspection]) -> list[Inspection]:
    """The records in use."""
    return [x for x in xs if x.active]


def audits_names(xs: list[Inspection]) -> list[str]:
    """The names, in order."""
    return sorted(x.name for x in xs)


def audits_total_findings(xs: list[Inspection]) -> int:
    """The sum of findings."""
    return sum(x.findings for x in xs)


def audits_total_duration(xs: list[Inspection]) -> float:
    """The sum of duration."""
    return sum(x.duration for x in xs)


def audits_average_duration(xs: list[Inspection]) -> float:
    """The mean of duration, 0 for no records."""
    if not xs:
        return 0.0
    return audits_total_duration(xs) / len(xs)


def audits_kind_label(k: InspectionKind) -> str:
    """The kind as people read it."""
    return k.value


def audits_kind_weight(k: InspectionKind) -> float:
    """How much a kind counts in a score."""
    match k:
        case InspectionKind.SAFETY:
            return 1.0
        case InspectionKind.STOCK:
            return 1.5
        case InspectionKind.TAX:
            return 2.0


def audits_describe(x: Inspection) -> str:
    """One record as text."""
    return f"{x.name} ({x.city}), {audits_kind_label(x.kind)}: {x.findings} findings, {x.duration:.2f} duration"


def audits_by_kind(xs: list[Inspection], k: InspectionKind) -> list[Inspection]:
    """The records of one kind."""
    return [x for x in xs if x.kind == k]


def audits_ranked(xs: list[Inspection]) -> list[Inspection]:
    """The records with the most findings first."""
    return sorted(xs, key=lambda x: -x.findings)


def audits_top(xs: list[Inspection], n: int) -> list[Inspection]:
    """The first few of the ranking."""
    return audits_ranked(xs)[:n]


def audits_validate(x: Inspection) -> list[str]:
    """What is wrong with a record."""
    errors = []
    if not x.name:
        errors.append("no name")
    if not x.city:
        errors.append("no city")
    if x.findings < 0:
        errors.append("negative findings")
    if x.duration < 0.0:
        errors.append("negative duration")
    return errors


def audits_score(x: Inspection) -> float:
    """The record with duration and findings weighed together."""
    return x.duration * audits_kind_weight(x.kind) + x.findings


def audits_row(x: Inspection) -> str:
    """A row of the export file."""
    return f"{x.id},{x.name},{x.city},{audits_kind_label(x.kind)},{x.findings},{x.duration:.2f}"


def audits_file(xs: list[Inspection]) -> str:
    """The export file."""
    return "\n".join(["id,name,city,kind,findings,duration", *(audits_row(x) for x in xs)])


def audits_per_city(xs: list[Inspection]) -> dict[str, int]:
    """The number of records per city."""
    m: dict[str, int] = {}
    for x in xs:
        m[x.city] = m.get(x.city, 0) + 1
    return m


def audits_over(xs: list[Inspection], limit: float) -> list[Inspection]:
    """The records above a limit of duration."""
    return [x for x in xs if x.duration > limit]


def audits_summary(xs: list[Inspection]) -> str:
    """A line for the dashboard."""
    return f"{len(xs)} inspection records, {len(audits_active(xs))} active, {audits_total_duration(xs):.2f} duration"
