from dataclasses import replace

from users import User, find_user


def rename_user(directory: list[User], user_id: int, new_name: str) -> list[User]:
    """Gives a user a new name (the name is trimmed and must not be empty)."""
    u = find_user(directory, user_id)
    if u.id == -1:
        raise ValueError(f"unknown user {user_id}")
    name = new_name.strip()
    if name == "":
        raise ValueError("empty name")
    return [replace(x, name=name) if x.id == user_id else x for x in directory]


def deactivate_user(directory: list[User], user_id: int) -> list[User]:
    """Removes a user from the directory."""
    u = find_user(directory, user_id)
    return [x for x in directory if x.id != u.id]


def list_users(directory: list[User]) -> list[str]:
    """One line per user, sorted by name: "1 alice <alice@example.com>"."""
    return [f"{u.id} {u.name} <{u.email}>" for u in sorted(directory, key=lambda u: u.name)]
