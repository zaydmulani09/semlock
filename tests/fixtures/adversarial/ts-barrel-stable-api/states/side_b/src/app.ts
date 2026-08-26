import { formatGreeting, User } from "./index";

export function welcome(u: User): string {
    return formatGreeting(u);
}
