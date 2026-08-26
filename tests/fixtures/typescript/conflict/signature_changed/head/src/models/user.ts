export interface User {
  name: string;
}

export function formatGreeting(
  user: User,
  punct: string,
  caseSensitive: boolean
): string {
  return "Hello, " + user.name + punct;
}
