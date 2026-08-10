/**
 * Account list filtering and sorting (blueprint §14).
 *
 * Kept as pure functions rather than inline component state so the behaviour is
 * directly testable: the controls previously rendered but did nothing, and a test
 * that only asserted a control exists would not have caught that.
 */

import type { Account } from "./types";

export type SortKey = "priority" | "fit" | "intent" | "confidence" | "unknowns";

export interface AccountFilters {
  search: string;
  state: string;
  industry: string;
  country: string;
  owner: string;
  tag: string;
  signal: "" | "with" | "without";
  sort: SortKey;
}

export const EMPTY_FILTERS: AccountFilters = {
  search: "",
  state: "",
  industry: "",
  country: "",
  owner: "",
  tag: "",
  signal: "",
  sort: "priority",
};

/**
 * Unresolved criteria for an account. The brief carries an explicit unknowns list,
 * but the accounts table has only the account, so this derives the count from the
 * qualification reasons the account already carries.
 */
export function unknownCount(account: Account): number {
  return account.qualification_reasons.filter(reason =>
    /unknown|unverified|remain/i.test(reason),
  ).length;
}

export function hasSignal(account: Account): boolean {
  return account.scores.intent.score > 0 || Boolean(account.top_signal_type);
}

/** Distinct non-empty values for a facet, ready to render as options. */
export function facetValues(
  accounts: Account[],
  key: "brief_state" | "industry" | "location" | "owner",
): string[] {
  const seen = new Set<string>();
  for (const account of accounts) {
    const value = account[key];
    // "Unverified" is a placeholder, not a real facet value worth offering.
    if (typeof value === "string" && value.trim() && value !== "Unverified") {
      seen.add(value);
    }
  }
  return [...seen].sort();
}

export function tagValues(accounts: Account[]): string[] {
  const seen = new Set<string>();
  for (const account of accounts) {
    for (const tag of account.tags ?? []) {
      if (tag.trim()) seen.add(tag);
    }
  }
  return [...seen].sort();
}

function sortValue(account: Account, key: SortKey): number {
  switch (key) {
    case "fit":
      return account.scores.fit.score;
    case "intent":
      return account.scores.intent.score;
    case "confidence":
      return account.scores.confidence.score;
    case "unknowns":
      return unknownCount(account);
    default:
      return account.scores.priority;
  }
}

export function filterAccounts(
  accounts: Account[],
  filters: AccountFilters,
): Account[] {
  const search = filters.search.trim().toLowerCase();
  const matched = accounts.filter(account => {
    if (
      search &&
      !account.name.toLowerCase().includes(search) &&
      !account.domain.toLowerCase().includes(search)
    ) {
      return false;
    }
    if (filters.state && account.brief_state !== filters.state) return false;
    if (filters.industry && account.industry !== filters.industry) return false;
    if (filters.country && account.location !== filters.country) return false;
    if (filters.owner && account.owner !== filters.owner) return false;
    if (filters.tag && !(account.tags ?? []).includes(filters.tag)) return false;
    if (filters.signal === "with" && !hasSignal(account)) return false;
    if (filters.signal === "without" && hasSignal(account)) return false;
    return true;
  });

  // Unknowns ascending: fewest open questions first is the useful direction.
  const ascending = filters.sort === "unknowns";
  return [...matched].sort((a, b) => {
    const delta = sortValue(a, filters.sort) - sortValue(b, filters.sort);
    return ascending ? delta : -delta;
  });
}

export function isFiltered(filters: AccountFilters): boolean {
  return (
    Boolean(filters.search.trim()) ||
    Boolean(filters.state) ||
    Boolean(filters.industry) ||
    Boolean(filters.country) ||
    Boolean(filters.owner) ||
    Boolean(filters.tag) ||
    Boolean(filters.signal)
  );
}
