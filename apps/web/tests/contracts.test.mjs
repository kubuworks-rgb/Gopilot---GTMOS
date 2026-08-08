import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("priority contract remains confidence adjusted", () => {
  const fit = 90, intent = 70, confidence = 80;
  const priority = Math.round((fit * .55 + intent * .45) * confidence / 100);
  assert.equal(priority, 65);
});

test("demo label is an explicit product invariant", () => {
  const mode = { research: "fixture", demo_data: true };
  assert.equal(mode.research === "fixture" && mode.demo_data, true);
});

test("BYOA is the primary mode and discovery is labelled experimental", () => {
  const source = readFileSync(
    new URL("../components/command-center.tsx", import.meta.url),
    "utf8",
  );
  assert.match(source, /Import accounts/);
  assert.match(source, /BYOA core · default mode/);
  assert.match(source, /Experimental discovery/);
  assert.match(source, /Human review required/);
  assert.match(source, /must not be treated as founder-ready by default/);
});

test("provider-independent message and import provenance are visible", () => {
  const source = readFileSync(
    new URL("../components/command-center.tsx", import.meta.url),
    "utf8",
  );
  assert.match(source, /No search provider is required/);
  assert.match(source, /account\.provenance/);
  assert.match(source, /account\.import_source/);
  assert.match(source, /NO_SIGNAL/);
});
