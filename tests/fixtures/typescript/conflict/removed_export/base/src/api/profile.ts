export interface Profile {
  handle: string;
}

export function fetchProfile(id: string): Profile {
  return { handle: "u-" + id };
}
