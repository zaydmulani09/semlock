import { fetchProfile } from "../api";
import type { Profile } from "../api";

export function widgetLabel(id: string): string {
  const p: Profile = fetchProfile(id);
  return "@" + p.handle;
}
