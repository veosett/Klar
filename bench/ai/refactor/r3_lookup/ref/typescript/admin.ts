import { User, find_user } from "./users";

/** Gives a user a new name (the name is trimmed and must not be empty). */
export function rename_user(directory: readonly User[], user_id: number, new_name: string): User[] {
  if (find_user(directory, user_id) === undefined) {
    throw new Error(`unknown user ${user_id}`);
  }
  const name = new_name.trim();
  if (name === "") {
    throw new Error("empty name");
  }
  return directory.map((x) => (x.id === user_id ? { ...x, name } : x));
}

/** Removes a user from the directory. */
export function deactivate_user(directory: readonly User[], user_id: number): User[] {
  if (find_user(directory, user_id) === undefined) {
    throw new Error(`unknown user ${user_id}`);
  }
  return directory.filter((x) => x.id !== user_id);
}

/** One line per user, sorted by name: "1 alice <alice@example.com>". */
export function list_users(directory: readonly User[]): string[] {
  return [...directory]
    .sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0))
    .map((u) => `${u.id} ${u.name} <${u.email}>`);
}
