export interface User {
  name: string;
}

export function formatGreeting(user: User, punct: string): string {
  return "Hello, " + user.name + punct;
}
