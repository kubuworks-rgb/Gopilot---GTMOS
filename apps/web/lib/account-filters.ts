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
  /** Score floors, 0 meaning "no floor". Scores are 0-100. */
  minPriority: number;
  minFit: number;
  minIntent: number;
  minConfidence: number;
  unknowns: "" | "with" | "without";
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
  minPriority: 0,
  minFit: 0,
  minIntent: 0,
  minConfidence: 0,
  unknowns: "",
  sort: "priority",
};

/**
 * Offered as floors rather than bands. "Fit is 60-79" is a question about the
 * scoring model; "show me everything at 60 or better" is the question a founder
 * deciding who to contact is actually asking.
 */
export const SCORE_THRESHOLDS = [80, 60, 40] as const;

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
    if (account.scores.priority < filters.minPriority) return false;
    if (account.scores.fit.score < filters.minFit) return false;
    if (account.scores.intent.score < filters.minIntent) return false;
    if (account.scores.confidence.score < filters.minConfidence) return false;
    // An account with open questions is not a worse account, it is a less
    // finished one, so this separates "ready to act on" from "needs a look"
    // rather than ranking them against each other.
    const unresolved = unknownCount(account) > 0;
    if (filters.unknowns === "with" && !unresolved) return false;
    if (filters.unknowns === "without" && unresolved) return false;
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
    Boolean(filters.signal) ||
    Boolean(filters.unknowns) ||
    filters.minPriority > 0 ||
    filters.minFit > 0 ||
    filters.minIntent > 0 ||
    filters.minConfidence > 0
  );
}
