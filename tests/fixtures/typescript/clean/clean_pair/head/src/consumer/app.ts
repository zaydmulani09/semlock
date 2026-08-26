import { greet } from "../feature/greeter";
import { shout } from "../feature/shouter";

export function banner(): string {
  return greet("world") + shout("world");
}
