from model import Tier


def points_for(total: float) -> int:
    """One point for every whole 10.00."""
    return int(total // 10)


def tier_after(spent: float) -> Tier:
    """The tier that a year of spending earns."""
    if spent >= 1000.0:
        return Tier.GOLD
    if spent >= 300.0:
        return Tier.SILVER
    return Tier.BASIC


def redeem_value(points: int) -> float:
    """The money that points are worth: 0.10 each."""
    return points * 0.1


def to_next_point(total: float) -> float:
    """Points still missing for the next whole 10.00."""
    return 10.0 - total % 10
