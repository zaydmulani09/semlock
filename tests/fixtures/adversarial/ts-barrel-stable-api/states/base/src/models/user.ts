export class User {
    email: string | null = null;

    greet(name: string): string {
        return `Hello, ${name}`;
    }
}

export function formatGreeting(user: User): string {
    return user.greet(user.email ?? "user");
}
