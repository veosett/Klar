import { User, find_user } from "./users";

/** A message that was sent from one user to another. */
export interface Message {
  readonly from_user: User;
  readonly to_user: User;
  readonly text: string;
}

/** The greeting for a user. */
export function greeting(directory: readonly User[], user_id: number): string {
  const u = find_user(directory, user_id);
  if (u === undefined) {
    return "hello, stranger";
  }
  return "hello, " + u.name;
}

/** Sends a message from one user id to another. */
export function send_message(directory: readonly User[], from_id: number, to_id: number, text: string): Message {
  const sender = find_user(directory, from_id);
  if (sender === undefined) {
    throw new Error(`unknown user ${from_id}`);
  }
  const receiver = find_user(directory, to_id);
  if (receiver === undefined) {
    throw new Error(`unknown user ${to_id}`);
  }
  return { from_user: sender, to_user: receiver, text };
}

/** Sends the greeting of the receiver as a message. */
export function send_greeting(directory: readonly User[], from_id: number, to_id: number): Message {
  const text = greeting(directory, to_id);
  return send_message(directory, from_id, to_id, text);
}

/** Sends the same text to several users; stops at the first failure. */
export function broadcast(directory: readonly User[], from_id: number, to_ids: readonly number[], text: string): Message[] {
  const sent: Message[] = [];
  for (const to_id of to_ids) {
    sent.push(send_message(directory, from_id, to_id, text));
  }
  return sent;
}

/** One line for a message: "alice -> bob: hi". */
export function format_message(m: Message): string {
  return `${m.from_user.name} -> ${m.to_user.name}: ${m.text}`;
}
