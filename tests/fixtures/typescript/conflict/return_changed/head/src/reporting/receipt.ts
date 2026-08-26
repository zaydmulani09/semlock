import { charge, Receipt } from "../payments/processor";

export function receiptLine(cents: number): number {
  const r: Receipt = charge(cents);
  return r.lines;
}
