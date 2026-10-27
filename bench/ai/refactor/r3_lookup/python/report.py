from users import User, find_user


def user_line(directory: list[User], user_id: int) -> str:
    """The report line of one user id: "2: bob <bob@example.com>"."""
    u = find_user(directory, user_id)
    return f"{u.id}: {u.name} <{u.email}>"


def report_lines(directory: list[User], ids: list[int]) -> list[str]:
    """The report lines of the listed ids, in the order given."""
    return [user_line(directory, i) for i in ids if find_user(directory, i).id != -1]


def summary(directory: list[User], ids: list[int]) -> str:
    """How many users the report lists."""
    known = len(report_lines(directory, ids))
    return f"{known} users"


def full_report(directory: list[User], ids: list[int]) -> str:
    """The summary, then one line per listed id."""
    return "\n".join([summary(directory, ids), *report_lines(directory, ids)])
