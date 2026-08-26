export class User {
    email: string | null = null;

    greet(name: string): string {
        return `Hello, ${name}`;
    }
}
