from dataclasses import dataclass

from users import User, find_user


@dataclass(frozen=True)
class Message:
    """A message that was sent from one user to another."""

    from_user: User
    to_user: User
    text: str


def greeting(directory: list[User], user_id: int) -> str:
    """The greeting for a user."""
    u = find_user(directory, user_id)
    if u is None:
        return "hello, stranger"
    return "hello, " + u.name


def send_message(directory: list[User], from_id: int, to_id: int, text: str) -> Message:
    """Sends a message from one user id to another."""
    sender = find_user(directory, from_id)
    if sender is None:
        raise ValueError(f"unknown user {from_id}")
    receiver = find_user(directory, to_id)
    if receiver is None:
        raise ValueError(f"unknown user {to_id}")
    return Message(from_user=sender, to_user=receiver, text=text)


def send_greeting(directory: list[User], from_id: int, to_id: int) -> Message:
    """Sends the greeting of the receiver as a message."""
    text = greeting(directory, to_id)
    return send_message(directory, from_id, to_id, text)


def broadcast(directory: list[User], from_id: int, to_ids: list[int], text: str) -> list[Message]:
    """Sends the same text to several users; stops at the first failure."""
    sent: list[Message] = []
    for to_id in to_ids:
        sent.append(send_message(directory, from_id, to_id, text))
    return sent


def format_message(m: Message) -> str:
    """One line for a message: "alice -> bob: hi"."""
    return f"{m.from_user.name} -> {m.to_user.name}: {m.text}"
