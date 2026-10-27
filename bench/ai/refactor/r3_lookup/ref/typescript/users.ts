/** A person in the directory. */
export interface User {
  readonly id: number;
  readonly name: string;
  readonly email: string;
}

/** The user with this id, or undefined when the id is unknown. */
export function find_user(directory: readonly User[], user_id: number): User | undefined {
  for (const u of directory) {
    if (u.id === user_id) {
      return u;
    }
  }
  return undefined;
}

/** The directory with one more user at the end. */
export function add_user(directory: readonly User[], user: User): User[] {
  return [...directory, user];
}

/** The email domain of a user ("" when the address has no @). */
export function email_domain(user: User): string {
  const parts = user.email.split("@");
  if (parts.length !== 2) {
    return "";
  }
  return parts[1];
}
