/**
 * Tests for the setup CLI's pure logic.
 *
 * The version gate decides whether someone can run this project at all, and the
 * config round-trip decides whether a returning user gets the mode they chose,
 * so both are pinned here rather than left to a manual run.
 *
 * Process supervision and the interactive prompts are not covered: they need a
 * real terminal and real child processes, and were verified by running the CLI
 * against a clean clone instead.
 */

import assert from "node:assert/strict";
import test from "node:test";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
  NODE_MIN,
  NODE_RECOMMENDED,
  PYTHON_MIN,
  atLeast,
  parseVersion,
} from "../lib/prereqs.mjs";
import { MODES, readConfig, writeConfig } from "../lib/wizard.mjs";

function scratch() {
  return mkdtempSync(join(tmpdir(), "gopilot-cli-test-"));
}

test("version parsing tolerates the shapes these tools actually print", () => {
  assert.deepEqual(parseVersion("v22.19.0"), [22, 19, 0]); // process.version
  assert.deepEqual(parseVersion("Python 3.13.7"), [3, 13, 7]); // python --version
  assert.deepEqual(parseVersion("3.11"), [3, 11, 0]); // missing patch
  assert.equal(parseVersion("not a version"), null);
});

test("the version gate compares numerically, not lexically", () => {
  // "3.9" > "3.11" as strings; this is the classic way a gate lets through
  // exactly the versions it exists to stop.
  assert.equal(atLeast("3.9.0", "3.11.0"), false);
  assert.equal(atLeast("3.11.0", "3.9.0"), true);
  assert.equal(atLeast("20.10.0", "20.9.0"), true);
});

test("the declared floors accept and reject the right versions", () => {
  assert.equal(atLeast("20.9.0", NODE_MIN), true, "exact minimum passes");
  assert.equal(atLeast("20.8.9", NODE_MIN), false);
  assert.equal(atLeast("22.19.0", NODE_MIN), true);
  assert.equal(atLeast("22.19.0", NODE_RECOMMENDED), true);
  assert.equal(atLeast("22.5.0", NODE_RECOMMENDED), false, "strip-types needs 22.6");
  assert.equal(atLeast("3.11.0", PYTHON_MIN), true, "StrEnum arrives in 3.11");
  assert.equal(atLeast("3.10.13", PYTHON_MIN), false);
});

test("demo mode records only the mode, and no secrets", () => {
  const dir = scratch();
  try {
    writeConfig(dir, MODES.demo, {});
    const text = readFileSync(join(dir, ".env.gopilot"), "utf8");
    assert.match(text, /RESEARCH_MODE=fixture/);
    assert.doesNotMatch(text, /EXA_API_KEY|TAVILY_API_KEY/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("each mode round-trips through the config file", () => {
  for (const mode of [MODES.demo, MODES.live, MODES.docker]) {
    const dir = scratch();
    try {
      writeConfig(dir, mode, {});
      assert.equal(readConfig(dir).mode.key, mode.key, `${mode.key} did not round-trip`);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  }
});

test("live and docker share RESEARCH_MODE and are told apart by the marker", () => {
  const dir = scratch();
  try {
    writeConfig(dir, MODES.docker, {});
    const text = readFileSync(join(dir, ".env.gopilot"), "utf8");
    assert.match(text, /RESEARCH_MODE=live/);
    assert.match(text, /GOPILOT_DOCKER_INFRA=true/);
    assert.equal(readConfig(dir).mode.key, "docker");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("optional keys are persisted, and blank answers are not written", () => {
  const dir = scratch();
  try {
    writeConfig(dir, MODES.live, { EXA_API_KEY: "abc123", TAVILY_API_KEY: "" });
    const text = readFileSync(join(dir, ".env.gopilot"), "utf8");
    assert.match(text, /EXA_API_KEY=abc123/);
    assert.doesNotMatch(text, /TAVILY_API_KEY=/, "a skipped key must not be written blank");
    assert.equal(readConfig(dir).env.EXA_API_KEY, "abc123");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("a missing or unusable config reads as absent, so the wizard runs", () => {
  const dir = scratch();
  try {
    assert.equal(readConfig(dir), null, "no file at all");
    writeFileSync(join(dir, ".env.gopilot"), "# only a comment\n", "utf8");
    assert.equal(readConfig(dir), null, "no RESEARCH_MODE means nothing was chosen");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("config parsing survives CRLF and stray whitespace", () => {
  // The file is written on whatever platform ran the wizard and may be read on
  // another; Windows checkouts also rewrite line endings.
  const dir = scratch();
  try {
    writeFileSync(
      join(dir, ".env.gopilot"),
      "# comment\r\n\r\n  RESEARCH_MODE = live  \r\nGOPILOT_DOCKER_INFRA=true\r\n",
      "utf8",
    );
    assert.equal(readConfig(dir).mode.key, "docker");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("interpreter discovery prefers PATH over the Windows launcher", async () => {
  // `py -3` resolves to a system-wide install, ignoring an activated
  // virtualenv and whatever CI put on PATH. Preferring it made the CLI check
  // one interpreter and install into another; on a Windows runner with the
  // dependencies already present that turned into a from-source wheel build.
  const source = readFileSync(new URL("../lib/prereqs.mjs", import.meta.url), "utf8");
  const block = source.slice(source.indexOf("PYTHON_CANDIDATES"));
  const order = [...block.matchAll(/\["(python3?|py)"/g)].map((m) => m[1]);
  assert.ok(order.length >= 3, "expected the candidate list to be found");
  assert.ok(
    order.indexOf("py") === -1 || order.indexOf("py") > order.indexOf("python"),
    `the py launcher must be a fallback, not the first choice: ${order.join(" > ")}`,
  );

  // And the interpreter it finds must be a real, usable one.
  const { findPython } = await import("../lib/prereqs.mjs");
  const found = findPython();
  assert.equal(found.ok, true, "no usable interpreter found on this machine");
  assert.equal(atLeast(found.version, PYTHON_MIN), true);
});

test("every mode maps to a script that package.json actually defines", () => {
  const scripts = JSON.parse(
    readFileSync(new URL("../../package.json", import.meta.url), "utf8"),
  ).scripts;
  for (const mode of Object.values(MODES)) {
    assert.ok(scripts[mode.script], `package.json has no "${mode.script}" script`);
  }
});
