export interface Receipt {
  lines: number;
}

export function charge(cents: number): Promise<Receipt> {
  return Promise.resolve({ lines: cents });
}
