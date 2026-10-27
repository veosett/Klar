import { User, find_user } from "./users";

/** The report line of one user id: "2: bob <bob@example.com>". */
export function user_line(directory: readonly User[], user_id: number): string {
  const u = find_user(directory, user_id);
  return `${u.id}: ${u.name} <${u.email}>`;
}

/** The report lines of the listed ids, in the order given. */
export function report_lines(directory: readonly User[], ids: readonly number[]): string[] {
  return ids.filter((i) => find_user(directory, i).id !== -1).map((i) => user_line(directory, i));
}

/** How many users the report lists. */
export function summary(directory: readonly User[], ids: readonly number[]): string {
  const known = report_lines(directory, ids).length;
  return `${known} users`;
}

/** The summary, then one line per listed id. */
export function full_report(directory: readonly User[], ids: readonly number[]): string {
  return [summary(directory, ids), ...report_lines(directory, ids)].join("\n");
}
