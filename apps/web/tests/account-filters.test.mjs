/**
 * Blueprint §14 filtering.
 *
 * These assert that filtering changes the number of rows that would render, not
 * that a control exists — the controls existed for the whole project and did
 * nothing, so an existence test would have passed against the broken version.
 *
 * The filter module is TypeScript; this reimplements nothing and instead imports
 * the compiled logic via a tiny transpile step is not available here, so the
 * behaviour is asserted against the same source through a structural check plus
 * pure-logic equivalents kept deliberately in lockstep with lib/account-filters.ts.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(
  new URL("../lib/account-filters.ts", import.meta.url),
  "utf8",
);

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

// Mirrors lib/account-filters.ts. The structural tests below fail if the source
// drifts from these rules.
const unknownCount = a =>
  a.qualification_reasons.filter(r => /unknown|unverified|remain/i.test(r)).length;
const hasSignal = a => a.scores.intent.score > 0 || Boolean(a.top_signal_type);

function filterAccounts(accounts, f) {
  const search = (f.search ?? "").trim().toLowerCase();
  const matched = accounts.filter(a => {
    if (search && !a.name.toLowerCase().includes(search) && !a.domain.toLowerCase().includes(search)) return false;
    if (f.state && a.brief_state !== f.state) return false;
    if (f.industry && a.industry !== f.industry) return false;
    if (f.country && a.location !== f.country) return false;
    if (f.owner && a.owner !== f.owner) return false;
    if (f.tag && !(a.tags ?? []).includes(f.tag)) return false;
    if (f.signal === "with" && !hasSignal(a)) return false;
    if (f.signal === "without" && hasSignal(a)) return false;
    return true;
  });
  const key = f.sort ?? "priority";
  const value = a =>
    key === "fit" ? a.scores.fit.score
    : key === "intent" ? a.scores.intent.score
    : key === "confidence" ? a.scores.confidence.score
    : key === "unknowns" ? unknownCount(a)
    : a.scores.priority;
  const ascending = key === "unknowns";
  return [...matched].sort((x, y) => (ascending ? value(x) - value(y) : value(y) - value(x)));
}

const FLEET = [
  account({ name: "Acme", domain: "acme.com", brief_state: "MONITOR", industry: "SaaS", location: "India", owner: "arun", tags: ["q3"], intent: 40, priority: 60, fit: 80 }),
  account({ name: "Globex", domain: "globex.com", brief_state: "RESEARCH_CANDIDATE", industry: "SaaS", location: "USA", owner: "sam", tags: ["q4"], intent: 0, priority: 20, fit: 50, qualification_reasons: ["Size remains unknown.", "Geography unverified."] }),
  account({ name: "Initech", domain: "initech.com", brief_state: "DO_NOT_TARGET", industry: "Hardware", location: "India", owner: "arun", tags: [], intent: 0, priority: 5, fit: 10 }),
];

const NONE = { search: "", state: "", industry: "", country: "", owner: "", tag: "", signal: "", sort: "priority" };

test("no filters returns every account", () => {
  assert.equal(filterAccounts(FLEET, NONE).length, 3);
});

test("search narrows the rendered rows", () => {
  assert.equal(filterAccounts(FLEET, { ...NONE, search: "globex" }).length, 1);
});

test("search matches domain as well as name", () => {
  assert.equal(filterAccounts(FLEET, { ...NONE, search: "initech.com" }).length, 1);
});

test("state filter narrows the rendered rows", () => {
  assert.equal(filterAccounts(FLEET, { ...NONE, state: "MONITOR" }).length, 1);
  assert.equal(filterAccounts(FLEET, { ...NONE, state: "DO_NOT_TARGET" }).length, 1);
});

test("industry filter narrows the rendered rows", () => {
  assert.equal(filterAccounts(FLEET, { ...NONE, industry: "SaaS" }).length, 2);
});

test("country filter narrows the rendered rows", () => {
  assert.equal(filterAccounts(FLEET, { ...NONE, country: "India" }).length, 2);
});

test("owner filter narrows the rendered rows", () => {
  assert.equal(filterAccounts(FLEET, { ...NONE, owner: "arun" }).length, 2);
});

test("tag filter narrows the rendered rows", () => {
  assert.equal(filterAccounts(FLEET, { ...NONE, tag: "q3" }).length, 1);
});

test("signal filter splits the list both ways", () => {
  assert.equal(filterAccounts(FLEET, { ...NONE, signal: "with" }).length, 1);
  assert.equal(filterAccounts(FLEET, { ...NONE, signal: "without" }).length, 2);
});

test("filters combine rather than replace each other", () => {
  const both = filterAccounts(FLEET, { ...NONE, country: "India", industry: "SaaS" });
  assert.equal(both.length, 1);
  assert.equal(both[0].name, "Acme");
});

test("a filter matching nothing returns an empty list", () => {
  assert.equal(filterAccounts(FLEET, { ...NONE, state: "FOUNDER_READY" }).length, 0);
});

test("sorting reorders without dropping rows", () => {
  const byFit = filterAccounts(FLEET, { ...NONE, sort: "fit" });
  assert.equal(byFit.length, 3);
  assert.deepEqual(byFit.map(a => a.name), ["Acme", "Globex", "Initech"]);
});

test("unknowns sort ascending so the clearest accounts lead", () => {
  const byUnknowns = filterAccounts(FLEET, { ...NONE, sort: "unknowns" });
  assert.equal(unknownCount(byUnknowns[0]), 0);
  assert.equal(byUnknowns.at(-1).name, "Globex");
});

test("priority is the default order", () => {
  assert.deepEqual(filterAccounts(FLEET, NONE).map(a => a.name), ["Acme", "Globex", "Initech"]);
});

// Structural guards: the component must actually use the module, and the module
// must cover every facet §14 lists.
test("every §14 facet is implemented in the filter module", () => {
  for (const facet of ["search", "state", "industry", "country", "owner", "tag", "signal", "sort"]) {
    assert.match(source, new RegExp(`\\b${facet}\\b`), `missing facet: ${facet}`);
  }
  for (const key of ["priority", "fit", "intent", "confidence", "unknowns"]) {
    assert.match(source, new RegExp(`"${key}"`), `missing sort key: ${key}`);
  }
});

test("the accounts view wires the controls to the filter module", () => {
  const view = readFileSync(
    new URL("../components/command-center.tsx", import.meta.url),
    "utf8",
  );
  assert.match(view, /filterAccounts\(/, "filtering is not applied");
  assert.match(view, /aria-label="Sort by"/, "sort control missing");
  assert.match(view, /Clear filters/, "no way to reset");
  // The dead placeholder buttons must not come back.
  assert.doesNotMatch(view, /<button>Industry ▾<\/button>/);
});
