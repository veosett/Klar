from model import Order, Status
from orders import item_count


def can_pack(s: Status) -> bool:
    """True when the warehouse may pack the order."""
    return s == Status.PAID


def packing_queue(os: list[Order]) -> list[Order]:
    """The orders waiting to be packed."""
    return [o for o in os if can_pack(o.status)]


def items_to_pack(os: list[Order]) -> int:
    """The items waiting to be packed."""
    return sum(item_count(o) for o in packing_queue(os))
