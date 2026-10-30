from dataclasses import dataclass
from enum import Enum


class RouteKind(Enum):
    """The kinds of route records."""
    URBAN = "Urban"
    RURAL = "Rural"
    EXPRESS = "Express"


@dataclass(frozen=True)
class Route:
    id: int
    name: str
    city: str
    kind: RouteKind
    stops: int
    distance: float
    active: bool


def routes_find(xs: list[Route], id: int) -> Route | None:
    """The record with this id."""
    return next((x for x in xs if x.id == id), None)


def routes_in_city(xs: list[Route], city: str) -> list[Route]:
    """The records of one city."""
    return [x for x in xs if x.city == city]


def routes_active(xs: list[Route]) -> list[Route]:
    """The records in use."""
    return [x for x in xs if x.active]


def routes_names(xs: list[Route]) -> list[str]:
    """The names, in order."""
    return sorted(x.name for x in xs)


def routes_total_stops(xs: list[Route]) -> int:
    """The sum of stops."""
    return sum(x.stops for x in xs)


def routes_total_distance(xs: list[Route]) -> float:
    """The sum of distance."""
    return sum(x.distance for x in xs)


def routes_average_distance(xs: list[Route]) -> float:
    """The mean of distance, 0 for no records."""
    if not xs:
        return 0.0
    return routes_total_distance(xs) / len(xs)


def routes_kind_label(k: RouteKind) -> str:
    """The kind as people read it."""
    return k.value


def routes_kind_weight(k: RouteKind) -> float:
    """How much a kind counts in a score."""
    match k:
        case RouteKind.URBAN:
            return 1.0
        case RouteKind.RURAL:
            return 1.5
        case RouteKind.EXPRESS:
            return 2.0


def routes_describe(x: Route) -> str:
    """One record as text."""
    return f"{x.name} ({x.city}), {routes_kind_label(x.kind)}: {x.stops} stops, {x.distance:.2f} distance"


def routes_by_kind(xs: list[Route], k: RouteKind) -> list[Route]:
    """The records of one kind."""
    return [x for x in xs if x.kind == k]


def routes_ranked(xs: list[Route]) -> list[Route]:
    """The records with the most stops first."""
    return sorted(xs, key=lambda x: -x.stops)


def routes_top(xs: list[Route], n: int) -> list[Route]:
    """The first few of the ranking."""
    return routes_ranked(xs)[:n]


def routes_validate(x: Route) -> list[str]:
    """What is wrong with a record."""
    errors = []
    if not x.name:
        errors.append("no name")
    if not x.city:
        errors.append("no city")
    if x.stops < 0:
        errors.append("negative stops")
    if x.distance < 0.0:
        errors.append("negative distance")
    return errors


def routes_score(x: Route) -> float:
    """The record with distance and stops weighed together."""
    return x.distance * routes_kind_weight(x.kind) + x.stops


def routes_row(x: Route) -> str:
    """A row of the export file."""
    return f"{x.id},{x.name},{x.city},{routes_kind_label(x.kind)},{x.stops},{x.distance:.2f}"


def routes_file(xs: list[Route]) -> str:
    """The export file."""
    return "\n".join(["id,name,city,kind,stops,distance", *(routes_row(x) for x in xs)])


def routes_per_city(xs: list[Route]) -> dict[str, int]:
    """The number of records per city."""
    m: dict[str, int] = {}
    for x in xs:
        m[x.city] = m.get(x.city, 0) + 1
    return m


def routes_over(xs: list[Route], limit: float) -> list[Route]:
    """The records above a limit of distance."""
    return [x for x in xs if x.distance > limit]


def routes_summary(xs: list[Route]) -> str:
    """A line for the dashboard."""
    return f"{len(xs)} route records, {len(routes_active(xs))} active, {routes_total_distance(xs):.2f} distance"
