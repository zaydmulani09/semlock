export function greet(name: string): string {
  return "hi " + name;
}

export function shout(name: string): string {
  return greet(name).toUpperCase() + "!";
}
