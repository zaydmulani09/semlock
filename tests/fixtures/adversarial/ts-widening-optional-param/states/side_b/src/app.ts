import { User } from "./models/user";

export function welcome(u: User): string {
    const message = u.greet("Ada");
    return message.toUpperCase();
}
