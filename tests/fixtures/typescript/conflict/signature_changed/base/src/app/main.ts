import { User, formatGreeting } from "../models/user";

export function welcome(user: User): string {
  return formatGreeting(user, ".");
}
