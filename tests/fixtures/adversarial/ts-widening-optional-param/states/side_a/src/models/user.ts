export class User {
    email: string | null = null;

    greet(name: string, punct = "!"): string {
        return `Hello, ${name}${punct}`;
    }
}

export function formatGreeting(user: User): string {
    return user.greet(user.email ?? "user");
}
