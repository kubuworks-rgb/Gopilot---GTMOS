/**
 * Blueprint §14 filtering, asserted against lib/account-filters.ts itself.
 *
 * These assert that filtering changes the number of rows that would render, not
 * that a control exists — the controls existed for the whole project and did
 * nothing, so an existence test would have passed against the broken version.
 *
 * An earlier version of this file reimplemented the filter rules locally and
 * checked the source text for them. That is the same failure one level up: it
 * would pass against a module that was never called. Node strips the types now,
 * so the real module runs.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  EMPTY_FILTERS,
  SCORE_THRESHOLDS,
  facetValues,
  filterAccounts,
  hasSignal,
  isFiltered,
  tagValues,
  unknownCount,
} from "../lib/account-filters.ts";

function account(overrides = {}) {
  return {
    id: overrides.id ?? Math.random().toString(36).slice(2),
    name: overrides.name ?? "Acme",
    domain: overrides.domain ?? "acme.com",
    industry: overrides.industry ?? "Unverified",
    location: overrides.location ?? "Unverified",
    owner: overrides.owner ?? null,
    tags: overrides.tags ?? [],
    brief_state: overrides.brief_state ?? "RESEARCH_CANDIDATE",
    top_signal_type: overrides.top_signal_type ?? null,
    qualification_reasons: overrides.qualification_reasons ?? [],
    scores: {
      fit: { score: overrides.fit ?? 50, components: [] },
      intent: { score: overrides.intent ?? 0, components: [] },
      confidence: { score: overrides.confidence ?? 50, components: [] },
      priority: overrides.priority ?? 10,
    },
  };
}

const NONE = EMPTY_FILTERS;

const FLEET = [
  account({
    name: "Acme",
    domain: "acme.com",
    industry: "SaaS",
    location: "India",
    owner: "arun",
    tags: ["q3"],
    brief_state: "RESEARCH_CANDIDATE",
    fit: 82,
    intent: 40,
    confidence: 71,
    priority: 74,
    top_signal_type: "HIRING",
    qualification_reasons: ["Company size remains unknown"],
  }),
  account({
    name: "Globex",
    domain: "globex.com",
    industry: "SaaS",
    location: "India",
    owner: "arun",
    tags: [],
    brief_state: "MONITOR",
    fit: 55,
    intent: 0,
    confidence: 44,
    priority: 31,
    qualification_reasons: [],
  }),
  account({
    name: "Initech",
    domain: "initech.com",
    industry: "Fintech",
    location: "Germany",
    owner: null,
    tags: [],
    brief_state: "DO_NOT_TARGET",
    fit: 20,
    intent: 0,
    confidence: 90,
    priority: 12,
    qualification_reasons: ["Funding stage unverified", "Headcount unknown"],
  }),
];

// The number of rows AccountTable would render for a given filter set.
const rows = filters => filterAccounts(FLEET, filters).length;

test("no filters renders every account", () => {
  assert.equal(rows(NONE), 3);
});

test("search narrows by name", () => {
  assert.equal(rows({ ...NONE, search: "globex" }), 1);
});

test("search narrows by domain", () => {
  assert.equal(rows({ ...NONE, search: "initech.com" }), 1);
});

test("state filters the list", () => {
  assert.equal(rows({ ...NONE, state: "MONITOR" }), 1);
  assert.equal(rows({ ...NONE, state: "DO_NOT_TARGET" }), 1);
});

test("industry filters the list", () => {
  assert.equal(rows({ ...NONE, industry: "SaaS" }), 2);
});

test("country filters the list", () => {
  assert.equal(rows({ ...NONE, country: "India" }), 2);
});

test("owner filters the list", () => {
  assert.equal(rows({ ...NONE, owner: "arun" }), 2);
});

test("tag filters the list", () => {
  assert.equal(rows({ ...NONE, tag: "q3" }), 1);
});

test("signal presence filters both ways", () => {
  assert.equal(rows({ ...NONE, signal: "with" }), 1);
  assert.equal(rows({ ...NONE, signal: "without" }), 2);
});

test("a priority floor drops everything below it", () => {
  assert.equal(rows({ ...NONE, minPriority: 40 }), 1);
  assert.equal(rows({ ...NONE, minPriority: 80 }), 0);
});

test("a fit floor drops everything below it", () => {
  assert.equal(rows({ ...NONE, minFit: 80 }), 1);
  assert.equal(rows({ ...NONE, minFit: 40 }), 2);
});

test("an intent floor drops accounts with no intent", () => {
  assert.equal(rows({ ...NONE, minIntent: 40 }), 1);
});

test("a confidence floor keeps a high-confidence disqualification", () => {
  // Initech scores 20 on fit and 90 on confidence: confident that it is a poor
  // fit. Confidence must not be conflated with desirability.
  const confident = filterAccounts(FLEET, { ...NONE, minConfidence: 80 });
  assert.deepEqual(confident.map(item => item.name), ["Initech"]);
});

test("unknowns splits resolved from unresolved", () => {
  assert.equal(rows({ ...NONE, unknowns: "with" }), 2);
  assert.equal(rows({ ...NONE, unknowns: "without" }), 1);
  assert.equal(
    rows({ ...NONE, unknowns: "with" }) + rows({ ...NONE, unknowns: "without" }),
    FLEET.length,
    "every account is on exactly one side of the split",
  );
});

test("filters combine rather than replace each other", () => {
  assert.equal(rows({ ...NONE, country: "India", industry: "SaaS" }), 2);
  assert.equal(rows({ ...NONE, country: "India", minFit: 80 }), 1);
  assert.equal(rows({ ...NONE, country: "Germany", industry: "SaaS" }), 0);
});

test("a filter matching nothing renders no rows rather than falling back to all", () => {
  assert.equal(rows({ ...NONE, state: "FOUNDER_READY" }), 0);
});

test("every offered threshold is a real option", () => {
  for (const threshold of SCORE_THRESHOLDS) {
    assert.ok(threshold > 0 && threshold <= 100);
  }
});

test("sorting reorders without dropping rows", () => {
  const byFit = filterAccounts(FLEET, { ...NONE, sort: "fit" });
  assert.equal(byFit.length, FLEET.length);
  assert.deepEqual(byFit.map(item => item.name), ["Acme", "Globex", "Initech"]);
});

test("fewest unknowns sorts ascending", () => {
  const byUnknowns = filterAccounts(FLEET, { ...NONE, sort: "unknowns" });
  assert.deepEqual(byUnknowns.map(item => item.name), ["Globex", "Acme", "Initech"]);
});

test("the default sort is priority, highest first", () => {
  assert.deepEqual(
    filterAccounts(FLEET, NONE).map(item => item.name),
    ["Acme", "Globex", "Initech"],
  );
});

test("unknownCount reads the qualification reasons", () => {
  assert.equal(unknownCount(FLEET[0]), 1);
  assert.equal(unknownCount(FLEET[1]), 0);
  assert.equal(unknownCount(FLEET[2]), 2);
});

test("an account has a signal from intent or from a signal type", () => {
  assert.equal(hasSignal(FLEET[0]), true);
  assert.equal(hasSignal(FLEET[1]), false);
});

test("facets offer only values actually present, never the placeholder", () => {
  assert.deepEqual(facetValues(FLEET, "industry"), ["Fintech", "SaaS"]);
  assert.deepEqual(facetValues(FLEET, "location"), ["Germany", "India"]);
  assert.deepEqual(facetValues(FLEET, "owner"), ["arun"]);
  assert.deepEqual(tagValues(FLEET), ["q3"]);

  const placeholder = [account({ industry: "Unverified", location: "Unverified" })];
  assert.deepEqual(facetValues(placeholder, "industry"), []);
});

test("isFiltered reports the count line honestly", () => {
  assert.equal(isFiltered(NONE), false);
  assert.equal(isFiltered({ ...NONE, sort: "fit" }), false, "sorting is not filtering");
  assert.equal(isFiltered({ ...NONE, minFit: 40 }), true);
  assert.equal(isFiltered({ ...NONE, unknowns: "with" }), true);
  assert.equal(isFiltered({ ...NONE, search: "  " }), false, "whitespace is not a search");
});

test("every filter in the type is wired into the control bar", () => {
  // The original defect was a control that rendered and did nothing. This catches
  // the inverse: a filter added to the model but never given a control.
  const view = readFileSync(
    new URL("../components/command-center.tsx", import.meta.url),
    "utf8",
  );
  for (const key of Object.keys(EMPTY_FILTERS)) {
    assert.match(view, new RegExp(`\\b${key}\\b`), `${key} has no control`);
  }
  assert.match(view, /filterAccounts\(/, "filtering is not applied");
});
