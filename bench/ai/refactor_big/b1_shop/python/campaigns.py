from dataclasses import dataclass
from enum import Enum


class CampaignKind(Enum):
    """The kinds of campaign records."""
    EMAIL = "Email"
    BANNER = "Banner"
    RADIO = "Radio"


@dataclass(frozen=True)
class Campaign:
    id: int
    name: str
    city: str
    kind: CampaignKind
    clicks: int
    budget: float
    active: bool


def campaigns_find(xs: list[Campaign], id: int) -> Campaign | None:
    """The record with this id."""
    return next((x for x in xs if x.id == id), None)


def campaigns_in_city(xs: list[Campaign], city: str) -> list[Campaign]:
    """The records of one city."""
    return [x for x in xs if x.city == city]


def campaigns_active(xs: list[Campaign]) -> list[Campaign]:
    """The records in use."""
    return [x for x in xs if x.active]


def campaigns_names(xs: list[Campaign]) -> list[str]:
    """The names, in order."""
    return sorted(x.name for x in xs)


def campaigns_total_clicks(xs: list[Campaign]) -> int:
    """The sum of clicks."""
    return sum(x.clicks for x in xs)


def campaigns_total_budget(xs: list[Campaign]) -> float:
    """The sum of budget."""
    return sum(x.budget for x in xs)


def campaigns_average_budget(xs: list[Campaign]) -> float:
    """The mean of budget, 0 for no records."""
    if not xs:
        return 0.0
    return campaigns_total_budget(xs) / len(xs)


def campaigns_kind_label(k: CampaignKind) -> str:
    """The kind as people read it."""
    return k.value


def campaigns_kind_weight(k: CampaignKind) -> float:
    """How much a kind counts in a score."""
    match k:
        case CampaignKind.EMAIL:
            return 1.0
        case CampaignKind.BANNER:
            return 1.5
        case CampaignKind.RADIO:
            return 2.0


def campaigns_describe(x: Campaign) -> str:
    """One record as text."""
    return f"{x.name} ({x.city}), {campaigns_kind_label(x.kind)}: {x.clicks} clicks, {x.budget:.2f} budget"


def campaigns_by_kind(xs: list[Campaign], k: CampaignKind) -> list[Campaign]:
    """The records of one kind."""
    return [x for x in xs if x.kind == k]


def campaigns_ranked(xs: list[Campaign]) -> list[Campaign]:
    """The records with the most clicks first."""
    return sorted(xs, key=lambda x: -x.clicks)


def campaigns_top(xs: list[Campaign], n: int) -> list[Campaign]:
    """The first few of the ranking."""
    return campaigns_ranked(xs)[:n]


def campaigns_validate(x: Campaign) -> list[str]:
    """What is wrong with a record."""
    errors = []
    if not x.name:
        errors.append("no name")
    if not x.city:
        errors.append("no city")
    if x.clicks < 0:
        errors.append("negative clicks")
    if x.budget < 0.0:
        errors.append("negative budget")
    return errors


def campaigns_score(x: Campaign) -> float:
    """The record with budget and clicks weighed together."""
    return x.budget * campaigns_kind_weight(x.kind) + x.clicks


def campaigns_row(x: Campaign) -> str:
    """A row of the export file."""
    return f"{x.id},{x.name},{x.city},{campaigns_kind_label(x.kind)},{x.clicks},{x.budget:.2f}"


def campaigns_file(xs: list[Campaign]) -> str:
    """The export file."""
    return "\n".join(["id,name,city,kind,clicks,budget", *(campaigns_row(x) for x in xs)])


def campaigns_per_city(xs: list[Campaign]) -> dict[str, int]:
    """The number of records per city."""
    m: dict[str, int] = {}
    for x in xs:
        m[x.city] = m.get(x.city, 0) + 1
    return m


def campaigns_over(xs: list[Campaign], limit: float) -> list[Campaign]:
    """The records above a limit of budget."""
    return [x for x in xs if x.budget > limit]


def campaigns_summary(xs: list[Campaign]) -> str:
    """A line for the dashboard."""
    return f"{len(xs)} campaign records, {len(campaigns_active(xs))} active, {campaigns_total_budget(xs):.2f} budget"
