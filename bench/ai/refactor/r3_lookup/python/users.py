from dataclasses import dataclass


@dataclass(frozen=True)
class User:
    """A person in the directory."""

    id: int
    name: str
    email: str


def find_user(directory: list[User], user_id: int) -> User:
    """The user with this id. Unknown ids give a placeholder user with id -1 and an empty name."""
    for u in directory:
        if u.id == user_id:
            return u
    return User(id=-1, name="", email="")


def add_user(directory: list[User], user: User) -> list[User]:
    """The directory with one more user at the end."""
    return [*directory, user]


def email_domain(user: User) -> str:
    """The email domain of a user ("" when the address has no @)."""
    parts = user.email.split("@")
    if len(parts) != 2:
        return ""
    return parts[1]
