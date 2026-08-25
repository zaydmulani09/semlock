export interface Receipt {
  lines: number;
}

export function charge(cents: number): Receipt {
  return { lines: cents };
}
