import { User, find_user } from "./users";

/** The report line of one user id: "2: bob <bob@example.com>". */
export function user_line(directory: readonly User[], user_id: number): string {
  const u = find_user(directory, user_id);
  if (u === undefined) {
    return `${user_id}: (unknown)`;
  }
  return `${u.id}: ${u.name} <${u.email}>`;
}

/** The report lines of the listed ids, in the order given (unknown ids are listed too). */
export function report_lines(directory: readonly User[], ids: readonly number[]): string[] {
  return ids.map((i) => user_line(directory, i));
}

/** How many ids the report lists and how many of them are unknown. */
export function summary(directory: readonly User[], ids: readonly number[]): string {
  const unknown = ids.filter((i) => find_user(directory, i) === undefined).length;
  return `${ids.length} listed, ${unknown} unknown`;
}

/** The summary, then one line per listed id. */
export function full_report(directory: readonly User[], ids: readonly number[]): string {
  return [summary(directory, ids), ...report_lines(directory, ids)].join("\n");
}
