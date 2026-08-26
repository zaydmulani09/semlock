import { Account } from "../entities/user";

export function label(account: Account): string {
  return account.email;
}

export function tag(account: Account): string {
  account.email = account.email.trim();
  return account.id;
}
