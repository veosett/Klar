from dataclasses import dataclass
from enum import Enum


class PartnerKind(Enum):
    """The kinds of partner records."""
    RESELLER = "Reseller"
    AFFILIATE = "Affiliate"
    AGENT = "Agent"


@dataclass(frozen=True)
class Partner:
    id: int
    name: str
    city: str
    kind: PartnerKind
    referrals: int
    share: float
    active: bool


def partners_find(xs: list[Partner], id: int) -> Partner | None:
    """The record with this id."""
    return next((x for x in xs if x.id == id), None)


def partners_in_city(xs: list[Partner], city: str) -> list[Partner]:
    """The records of one city."""
    return [x for x in xs if x.city == city]


def partners_active(xs: list[Partner]) -> list[Partner]:
    """The records in use."""
    return [x for x in xs if x.active]


def partners_names(xs: list[Partner]) -> list[str]:
    """The names, in order."""
    return sorted(x.name for x in xs)


def partners_total_referrals(xs: list[Partner]) -> int:
    """The sum of referrals."""
    return sum(x.referrals for x in xs)


def partners_total_share(xs: list[Partner]) -> float:
    """The sum of share."""
    return sum(x.share for x in xs)


def partners_average_share(xs: list[Partner]) -> float:
    """The mean of share, 0 for no records."""
    if not xs:
        return 0.0
    return partners_total_share(xs) / len(xs)


def partners_kind_label(k: PartnerKind) -> str:
    """The kind as people read it."""
    return k.value


def partners_kind_weight(k: PartnerKind) -> float:
    """How much a kind counts in a score."""
    match k:
        case PartnerKind.RESELLER:
            return 1.0
        case PartnerKind.AFFILIATE:
            return 1.5
        case PartnerKind.AGENT:
            return 2.0


def partners_describe(x: Partner) -> str:
    """One record as text."""
    return f"{x.name} ({x.city}), {partners_kind_label(x.kind)}: {x.referrals} referrals, {x.share:.2f} share"


def partners_by_kind(xs: list[Partner], k: PartnerKind) -> list[Partner]:
    """The records of one kind."""
    return [x for x in xs if x.kind == k]


def partners_ranked(xs: list[Partner]) -> list[Partner]:
    """The records with the most referrals first."""
    return sorted(xs, key=lambda x: -x.referrals)


def partners_top(xs: list[Partner], n: int) -> list[Partner]:
    """The first few of the ranking."""
    return partners_ranked(xs)[:n]


def partners_validate(x: Partner) -> list[str]:
    """What is wrong with a record."""
    errors = []
    if not x.name:
        errors.append("no name")
    if not x.city:
        errors.append("no city")
    if x.referrals < 0:
        errors.append("negative referrals")
    if x.share < 0.0:
        errors.append("negative share")
    return errors


def partners_score(x: Partner) -> float:
    """The record with share and referrals weighed together."""
    return x.share * partners_kind_weight(x.kind) + x.referrals


def partners_row(x: Partner) -> str:
    """A row of the export file."""
    return f"{x.id},{x.name},{x.city},{partners_kind_label(x.kind)},{x.referrals},{x.share:.2f}"


def partners_file(xs: list[Partner]) -> str:
    """The export file."""
    return "\n".join(["id,name,city,kind,referrals,share", *(partners_row(x) for x in xs)])


def partners_per_city(xs: list[Partner]) -> dict[str, int]:
    """The number of records per city."""
    m: dict[str, int] = {}
    for x in xs:
        m[x.city] = m.get(x.city, 0) + 1
    return m


def partners_over(xs: list[Partner], limit: float) -> list[Partner]:
    """The records above a limit of share."""
    return [x for x in xs if x.share > limit]


def partners_summary(xs: list[Partner]) -> str:
    """A line for the dashboard."""
    return f"{len(xs)} partner records, {len(partners_active(xs))} active, {partners_total_share(xs):.2f} share"
