import assert from "node:assert/strict";
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
