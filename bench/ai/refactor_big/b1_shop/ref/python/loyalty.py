from model import Tier


def points_for(total: int) -> int:
    """One point for every whole 10.00."""
    return total // 1000


def tier_after(spent: int) -> Tier:
    """The tier that a year of spending earns."""
    if spent >= 100000:
        return Tier.GOLD
    if spent >= 30000:
        return Tier.SILVER
    return Tier.BASIC


def redeem_value(points: int) -> int:
    """The money that points are worth: 0.10 each."""
    return points * 10


def to_next_point(total: int) -> int:
    """Points still missing for the next whole 10.00."""
    return 1000 - total % 1000
