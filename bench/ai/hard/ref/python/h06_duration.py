import re


def duration(s: str) -> int:
    m = re.fullmatch(r"(?:([0-9]+)d)?(?:([0-9]+)h)?(?:([0-9]+)m)?(?:([0-9]+)s)?", s)
    if s == "" or m is None:
        raise ValueError("invalid duration")
    d, h, mi, sec = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + sec
