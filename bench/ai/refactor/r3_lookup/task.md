## Change request: `find_user` returns an optional value

At the moment `find_user(directory, user_id)` returns a placeholder user (id -1, empty name) when the id is unknown, and some callers forget to check for it. Remove the placeholder: `find_user` must return an optional user (Klar `Option[User]`, Python `User | None`, TypeScript `User | undefined`), and every caller must handle the missing user explicitly. Nothing may use a placeholder user any more.

Errors keep the type they have today (Klar `Err(text)` in a `Result`, Python `raise ValueError(text)`, TypeScript `throw new Error(text)`). Exact rules and texts (N is the id as a decimal number):

- `messages.send_message`: an unknown sender fails with the error `unknown user N` (N is the sender id); an unknown receiver fails with `unknown user N` (N is the receiver id). The sender is checked before the receiver, so with both unknown the error names the sender. `send_greeting` and `broadcast` pass these errors on (`broadcast` stops at the first failure).
- `messages.greeting(directory, user_id)`: `hello, NAME` for a known user, `hello, stranger` for an unknown id.
- `admin.rename_user`: an unknown id fails with `unknown user N`, checked before the empty-name check (which still fails with `empty name`).
- `admin.deactivate_user`: an unknown id fails with `unknown user N` (today it silently returns the directory unchanged).
- `report.user_line(directory, user_id)`: `ID: NAME <EMAIL>` for a known user, `N: (unknown)` for an unknown id.
- `report.report_lines(directory, ids)`: one line per id, in the order given, unknown ids included (today they are skipped).
- `report.summary(directory, ids)`: `T listed, U unknown` where T is the number of ids given and U how many of them are unknown (today: `K users`, K = the known ones). `full_report` is unchanged: the summary line, then the lines, joined by `\n`.

Everything else keeps its behaviour and its signature.
