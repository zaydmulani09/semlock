import { User } from "./user";

export function formatGreeting(user: User): string {
    return user.greet(user.email ?? "user");
}
