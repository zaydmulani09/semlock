import { greet } from "../feature/greeter";

export function banner(): string {
  return greet("world");
}
