import sys
from typing import Any, Callable

from admin import deactivate_user, list_users, rename_user
from messages import broadcast, format_message, greeting, send_greeting, send_message
from report import full_report, report_lines, summary, user_line
from users import User, find_user

failures = 0


def check(what: str, got: Any, expected: Any) -> None:
    global failures
    if got != expected:
        failures += 1
        print(f"FAIL: {what}, got {got!r}, expected {expected!r}")


def outcome(f: Callable[[], Any]) -> Any:
    """('ok', value) or ('error', message)."""
    try:
        return ("ok", f())
    except Exception as e:  # noqa: BLE001
        return ("error", str(e))


def sample() -> list[User]:
    return [
        User(2, "bob", "bob@example.org"),
        User(3, "carol", "carol@example.com"),
        User(1, "alice", "alice@example.com"),
    ]


def names(directory: list[User]) -> list[str]:
    return [u.name for u in directory]


def name_of(u: User | None) -> str | None:
    return None if u is None else u.name


check("find_user finds a known id", name_of(find_user(sample(), 2)), "bob")
check("find_user gives None for an unknown id", find_user(sample(), 99), None)

check("send_message works for known users",
      outcome(lambda: format_message(send_message(sample(), 1, 2, "hi"))), ("ok", "alice -> bob: hi"))
check("send_message fails for an unknown sender",
      outcome(lambda: send_message(sample(), 99, 2, "hi")), ("error", "unknown user 99"))
check("send_message fails for an unknown receiver",
      outcome(lambda: send_message(sample(), 1, 77, "hi")), ("error", "unknown user 77"))
check("send_message checks the sender before the receiver",
      outcome(lambda: send_message(sample(), 99, 77, "hi")), ("error", "unknown user 99"))

check("greeting of a known user", greeting(sample(), 2), "hello, bob")
check("greeting of an unknown id", greeting(sample(), 99), "hello, stranger")
check("send_greeting carries the receiver's greeting",
      outcome(lambda: send_greeting(sample(), 1, 3).text), ("ok", "hello, carol"))
check("send_greeting to an unknown receiver fails",
      outcome(lambda: send_greeting(sample(), 1, 77)), ("error", "unknown user 77"))

check("broadcast reaches everybody",
      outcome(lambda: [m.to_user.name for m in broadcast(sample(), 1, [2, 3], "news")]), ("ok", ["bob", "carol"]))
check("broadcast stops at an unknown receiver",
      outcome(lambda: broadcast(sample(), 1, [2, 55, 3], "news")), ("error", "unknown user 55"))

check("rename_user renames a known user",
      outcome(lambda: names(rename_user(sample(), 2, "  robert "))), ("ok", ["robert", "carol", "alice"]))
check("rename_user fails for an unknown id",
      outcome(lambda: rename_user(sample(), 99, "x")), ("error", "unknown user 99"))
check("rename_user rejects an empty name",
      outcome(lambda: rename_user(sample(), 2, "   ")), ("error", "empty name"))

check("deactivate_user removes a known user",
      outcome(lambda: names(deactivate_user(sample(), 3))), ("ok", ["bob", "alice"]))
check("deactivate_user fails for an unknown id",
      outcome(lambda: deactivate_user(sample(), 99)), ("error", "unknown user 99"))

check("list_users is sorted by name", list_users(sample()), [
    "1 alice <alice@example.com>",
    "2 bob <bob@example.org>",
    "3 carol <carol@example.com>",
])

check("user_line of a known user", user_line(sample(), 2), "2: bob <bob@example.org>")
check("user_line of an unknown id", user_line(sample(), 99), "99: (unknown)")
check("report_lines lists unknown ids too", report_lines(sample(), [1, 99, 3]), [
    "1: alice <alice@example.com>",
    "99: (unknown)",
    "3: carol <carol@example.com>",
])
check("summary counts listed and unknown ids", summary(sample(), [1, 99, 3, 98]), "4 listed, 2 unknown")
check("summary of an empty report", summary(sample(), []), "0 listed, 0 unknown")
check("full_report", full_report(sample(), [2, 99]), "2 listed, 1 unknown\n2: bob <bob@example.org>\n99: (unknown)")

sys.exit(1 if failures else 0)
