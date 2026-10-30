from dataclasses import dataclass
from enum import Enum


class TicketKind(Enum):
    """The kinds of ticket records."""
    QUESTION = "Question"
    COMPLAINT = "Complaint"
    REQUEST = "Request"


@dataclass(frozen=True)
class Ticket:
    id: int
    name: str
    city: str
    kind: TicketKind
    replies: int
    hours: float
    active: bool


def tickets_find(xs: list[Ticket], id: int) -> Ticket | None:
    """The record with this id."""
    return next((x for x in xs if x.id == id), None)


def tickets_in_city(xs: list[Ticket], city: str) -> list[Ticket]:
    """The records of one city."""
    return [x for x in xs if x.city == city]


def tickets_active(xs: list[Ticket]) -> list[Ticket]:
    """The records in use."""
    return [x for x in xs if x.active]


def tickets_names(xs: list[Ticket]) -> list[str]:
    """The names, in order."""
    return sorted(x.name for x in xs)


def tickets_total_replies(xs: list[Ticket]) -> int:
    """The sum of replies."""
    return sum(x.replies for x in xs)


def tickets_total_hours(xs: list[Ticket]) -> float:
    """The sum of hours."""
    return sum(x.hours for x in xs)


def tickets_average_hours(xs: list[Ticket]) -> float:
    """The mean of hours, 0 for no records."""
    if not xs:
        return 0.0
    return tickets_total_hours(xs) / len(xs)


def tickets_kind_label(k: TicketKind) -> str:
    """The kind as people read it."""
    return k.value


def tickets_kind_weight(k: TicketKind) -> float:
    """How much a kind counts in a score."""
    match k:
        case TicketKind.QUESTION:
            return 1.0
        case TicketKind.COMPLAINT:
            return 1.5
        case TicketKind.REQUEST:
            return 2.0


def tickets_describe(x: Ticket) -> str:
    """One record as text."""
    return f"{x.name} ({x.city}), {tickets_kind_label(x.kind)}: {x.replies} replies, {x.hours:.2f} hours"


def tickets_by_kind(xs: list[Ticket], k: TicketKind) -> list[Ticket]:
    """The records of one kind."""
    return [x for x in xs if x.kind == k]


def tickets_ranked(xs: list[Ticket]) -> list[Ticket]:
    """The records with the most replies first."""
    return sorted(xs, key=lambda x: -x.replies)


def tickets_top(xs: list[Ticket], n: int) -> list[Ticket]:
    """The first few of the ranking."""
    return tickets_ranked(xs)[:n]


def tickets_validate(x: Ticket) -> list[str]:
    """What is wrong with a record."""
    errors = []
    if not x.name:
        errors.append("no name")
    if not x.city:
        errors.append("no city")
    if x.replies < 0:
        errors.append("negative replies")
    if x.hours < 0.0:
        errors.append("negative hours")
    return errors


def tickets_score(x: Ticket) -> float:
    """The record with hours and replies weighed together."""
    return x.hours * tickets_kind_weight(x.kind) + x.replies


def tickets_row(x: Ticket) -> str:
    """A row of the export file."""
    return f"{x.id},{x.name},{x.city},{tickets_kind_label(x.kind)},{x.replies},{x.hours:.2f}"


def tickets_file(xs: list[Ticket]) -> str:
    """The export file."""
    return "\n".join(["id,name,city,kind,replies,hours", *(tickets_row(x) for x in xs)])


def tickets_per_city(xs: list[Ticket]) -> dict[str, int]:
    """The number of records per city."""
    m: dict[str, int] = {}
    for x in xs:
        m[x.city] = m.get(x.city, 0) + 1
    return m


def tickets_over(xs: list[Ticket], limit: float) -> list[Ticket]:
    """The records above a limit of hours."""
    return [x for x in xs if x.hours > limit]


def tickets_summary(xs: list[Ticket]) -> str:
    """A line for the dashboard."""
    return f"{len(xs)} ticket records, {len(tickets_active(xs))} active, {tickets_total_hours(xs):.2f} hours"
