from users import User, find_user


def user_line(directory: list[User], user_id: int) -> str:
    """The report line of one user id: "2: bob <bob@example.com>"."""
    u = find_user(directory, user_id)
    if u is None:
        return f"{user_id}: (unknown)"
    return f"{u.id}: {u.name} <{u.email}>"


def report_lines(directory: list[User], ids: list[int]) -> list[str]:
    """The report lines of the listed ids, in the order given (unknown ids are listed too)."""
    return [user_line(directory, i) for i in ids]


def summary(directory: list[User], ids: list[int]) -> str:
    """How many ids the report lists and how many of them are unknown."""
    unknown = sum(1 for i in ids if find_user(directory, i) is None)
    return f"{len(ids)} listed, {unknown} unknown"


def full_report(directory: list[User], ids: list[int]) -> str:
    """The summary, then one line per listed id."""
    return "\n".join([summary(directory, ids), *report_lines(directory, ids)])
