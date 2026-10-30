from dataclasses import dataclass
from enum import Enum


class ContractKind(Enum):
    """The kinds of contract records."""
    LEASE = "Lease"
    SERVICE = "Service"
    LICENCE = "Licence"


@dataclass(frozen=True)
class Contract:
    id: int
    name: str
    city: str
    kind: ContractKind
    months: int
    fee: float
    active: bool


def contracts_find(xs: list[Contract], id: int) -> Contract | None:
    """The record with this id."""
    return next((x for x in xs if x.id == id), None)


def contracts_in_city(xs: list[Contract], city: str) -> list[Contract]:
    """The records of one city."""
    return [x for x in xs if x.city == city]


def contracts_active(xs: list[Contract]) -> list[Contract]:
    """The records in use."""
    return [x for x in xs if x.active]


def contracts_names(xs: list[Contract]) -> list[str]:
    """The names, in order."""
    return sorted(x.name for x in xs)


def contracts_total_months(xs: list[Contract]) -> int:
    """The sum of months."""
    return sum(x.months for x in xs)


def contracts_total_fee(xs: list[Contract]) -> float:
    """The sum of fee."""
    return sum(x.fee for x in xs)


def contracts_average_fee(xs: list[Contract]) -> float:
    """The mean of fee, 0 for no records."""
    if not xs:
        return 0.0
    return contracts_total_fee(xs) / len(xs)


def contracts_kind_label(k: ContractKind) -> str:
    """The kind as people read it."""
    return k.value


def contracts_kind_weight(k: ContractKind) -> float:
    """How much a kind counts in a score."""
    match k:
        case ContractKind.LEASE:
            return 1.0
        case ContractKind.SERVICE:
            return 1.5
        case ContractKind.LICENCE:
            return 2.0


def contracts_describe(x: Contract) -> str:
    """One record as text."""
    return f"{x.name} ({x.city}), {contracts_kind_label(x.kind)}: {x.months} months, {x.fee:.2f} fee"


def contracts_by_kind(xs: list[Contract], k: ContractKind) -> list[Contract]:
    """The records of one kind."""
    return [x for x in xs if x.kind == k]


def contracts_ranked(xs: list[Contract]) -> list[Contract]:
    """The records with the most months first."""
    return sorted(xs, key=lambda x: -x.months)


def contracts_top(xs: list[Contract], n: int) -> list[Contract]:
    """The first few of the ranking."""
    return contracts_ranked(xs)[:n]


def contracts_validate(x: Contract) -> list[str]:
    """What is wrong with a record."""
    errors = []
    if not x.name:
        errors.append("no name")
    if not x.city:
        errors.append("no city")
    if x.months < 0:
        errors.append("negative months")
    if x.fee < 0.0:
        errors.append("negative fee")
    return errors


def contracts_score(x: Contract) -> float:
    """The record with fee and months weighed together."""
    return x.fee * contracts_kind_weight(x.kind) + x.months


def contracts_row(x: Contract) -> str:
    """A row of the export file."""
    return f"{x.id},{x.name},{x.city},{contracts_kind_label(x.kind)},{x.months},{x.fee:.2f}"


def contracts_file(xs: list[Contract]) -> str:
    """The export file."""
    return "\n".join(["id,name,city,kind,months,fee", *(contracts_row(x) for x in xs)])


def contracts_per_city(xs: list[Contract]) -> dict[str, int]:
    """The number of records per city."""
    m: dict[str, int] = {}
    for x in xs:
        m[x.city] = m.get(x.city, 0) + 1
    return m


def contracts_over(xs: list[Contract], limit: float) -> list[Contract]:
    """The records above a limit of fee."""
    return [x for x in xs if x.fee > limit]


def contracts_summary(xs: list[Contract]) -> str:
    """A line for the dashboard."""
    return f"{len(xs)} contract records, {len(contracts_active(xs))} active, {contracts_total_fee(xs):.2f} fee"
