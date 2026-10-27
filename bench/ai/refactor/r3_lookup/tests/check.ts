import { deactivate_user, list_users, rename_user } from "./admin";
import { broadcast, format_message, greeting, send_greeting, send_message } from "./messages";
import { full_report, report_lines, summary, user_line } from "./report";
import { User, find_user } from "./users";

declare const process: { exit(code: number): never };

let failures = 0;

function check(what: string, got: unknown, expected: unknown): void {
  const g = JSON.stringify(got === undefined ? "undefined" : got);
  const e = JSON.stringify(expected === undefined ? "undefined" : expected);
  if (g !== e) {
    failures += 1;
    console.log(`FAIL: ${what}, got ${g}, expected ${e}`);
  }
}

/** ["ok", value] or ["error", message]. */
function outcome(f: () => unknown): [string, unknown] {
  try {
    return ["ok", f()];
  } catch (e) {
    return ["error", e instanceof Error ? e.message : String(e)];
  }
}

function sample(): User[] {
  return [
    { id: 2, name: "bob", email: "bob@example.org" },
    { id: 3, name: "carol", email: "carol@example.com" },
    { id: 1, name: "alice", email: "alice@example.com" },
  ];
}

function names(directory: readonly User[]): string[] {
  return directory.map((u) => u.name);
}

function name_of(u: User | undefined): string | undefined {
  return u === undefined ? undefined : u.name;
}

check("find_user finds a known id", name_of(find_user(sample(), 2)), "bob");
check("find_user gives None for an unknown id", find_user(sample(), 99), undefined);

check("send_message works for known users",
  outcome(() => format_message(send_message(sample(), 1, 2, "hi"))), ["ok", "alice -> bob: hi"]);
check("send_message fails for an unknown sender",
  outcome(() => send_message(sample(), 99, 2, "hi")), ["error", "unknown user 99"]);
check("send_message fails for an unknown receiver",
  outcome(() => send_message(sample(), 1, 77, "hi")), ["error", "unknown user 77"]);
check("send_message checks the sender before the receiver",
  outcome(() => send_message(sample(), 99, 77, "hi")), ["error", "unknown user 99"]);

check("greeting of a known user", greeting(sample(), 2), "hello, bob");
check("greeting of an unknown id", greeting(sample(), 99), "hello, stranger");
check("send_greeting carries the receiver's greeting",
  outcome(() => send_greeting(sample(), 1, 3).text), ["ok", "hello, carol"]);
check("send_greeting to an unknown receiver fails",
  outcome(() => send_greeting(sample(), 1, 77)), ["error", "unknown user 77"]);

check("broadcast reaches everybody",
  outcome(() => broadcast(sample(), 1, [2, 3], "news").map((m) => m.to_user.name)), ["ok", ["bob", "carol"]]);
check("broadcast stops at an unknown receiver",
  outcome(() => broadcast(sample(), 1, [2, 55, 3], "news")), ["error", "unknown user 55"]);

check("rename_user renames a known user",
  outcome(() => names(rename_user(sample(), 2, "  robert "))), ["ok", ["robert", "carol", "alice"]]);
check("rename_user fails for an unknown id",
  outcome(() => rename_user(sample(), 99, "x")), ["error", "unknown user 99"]);
check("rename_user rejects an empty name",
  outcome(() => rename_user(sample(), 2, "   ")), ["error", "empty name"]);

check("deactivate_user removes a known user",
  outcome(() => names(deactivate_user(sample(), 3))), ["ok", ["bob", "alice"]]);
check("deactivate_user fails for an unknown id",
  outcome(() => deactivate_user(sample(), 99)), ["error", "unknown user 99"]);

check("list_users is sorted by name", list_users(sample()), [
  "1 alice <alice@example.com>",
  "2 bob <bob@example.org>",
  "3 carol <carol@example.com>",
]);

check("user_line of a known user", user_line(sample(), 2), "2: bob <bob@example.org>");
check("user_line of an unknown id", user_line(sample(), 99), "99: (unknown)");
check("report_lines lists unknown ids too", report_lines(sample(), [1, 99, 3]), [
  "1: alice <alice@example.com>",
  "99: (unknown)",
  "3: carol <carol@example.com>",
]);
check("summary counts listed and unknown ids", summary(sample(), [1, 99, 3, 98]), "4 listed, 2 unknown");
check("summary of an empty report", summary(sample(), []), "0 listed, 0 unknown");
check("full_report", full_report(sample(), [2, 99]), "2 listed, 1 unknown\n2: bob <bob@example.org>\n99: (unknown)");

process.exit(failures > 0 ? 1 : 0);
