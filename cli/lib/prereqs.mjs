/**
 * Environment detection for the GoPilot setup CLI.
 *
 * Every version floor here was derived from what the project actually uses, not
 * from a guess:
 *
 *   Node >= 20.9.0   next@16 declares it in its own `engines` field.
 *   Node >= 22.6.0   only needed for `npm run test`, which runs the web suite
 *                    with --experimental-strip-types. Running the app does not
 *                    need it, so this is a warning rather than a hard failure.
 *   Python >= 3.11   StrEnum and datetime.UTC are used throughout apps/api.
 *                    Nothing in the tree uses a 3.12+ only feature.
 */

import { spawnSync } from "node:child_process";

export const NODE_MIN = "20.9.0";
export const NODE_RECOMMENDED = "22.6.0";
export const PYTHON_MIN = "3.11.0";

/** Windows resolves `npm` to npm.cmd; POSIX to a shell script. */
export const NPM = process.platform === "win32" ? "npm.cmd" : "npm";

/**
 * Node refuses to spawn .cmd/.bat without a shell (CVE-2024-27980), so `npm` on
 * Windows -- which resolves to npm.cmd -- needs shell:true. Every argument list
 * passed with it is a hard-coded literal, never user input, so there is nothing
 * to inject.
 *
 * This applies to npm ONLY. python, py, docker and alembic are real .exe files
 * that spawn directly, and routing them through a shell actively breaks them:
 * cmd.exe re-parses the arguments, so `-c "import fastapi, uvicorn"` arrives as
 * several broken fragments and the check fails against a perfectly good
 * install. That bug was caught by running this CLI, not by reading it.
 */
export const NPM_NEEDS_SHELL = process.platform === "win32";

export function parseVersion(text) {
  const match = String(text).match(/(\d+)\.(\d+)(?:\.(\d+))?/);
  if (!match) return null;
  return [Number(match[1]), Number(match[2]), Number(match[3] ?? 0)];
}

export function atLeast(actual, minimum) {
  const left = parseVersion(actual);
  const right = parseVersion(minimum);
  if (!left || !right) return false;
  for (let index = 0; index < 3; index += 1) {
    if (left[index] > right[index]) return true;
    if (left[index] < right[index]) return false;
  }
  return true;
}

/** Run a command for its output. Returns null on any failure, never throws. */
export function tryRun(command, args, { timeout = 15_000 } = {}) {
  try {
    const result = spawnSync(command, args, {
      encoding: "utf8",
      timeout,
      windowsHide: true,
    });
    if (result.error || result.status !== 0) return null;
    // Older Pythons print --version to stderr, so both streams are considered.
    return `${result.stdout ?? ""}${result.stderr ?? ""}`.trim();
  } catch {
    return null;
  }
}

export function checkNode() {
  const version = process.versions.node;
  return {
    name: "Node.js",
    version,
    ok: atLeast(version, NODE_MIN),
    recommended: atLeast(version, NODE_RECOMMENDED),
  };
}

/**
 * Find a usable interpreter.
 *
 * Order matters, and getting it wrong is not cosmetic. `py -3` was tried first
 * on Windows to dodge the Microsoft Store alias stub, but the launcher resolves
 * to a system-wide install and ignores both an activated virtualenv and
 * whatever a CI runner has put on PATH. The result was the CLI checking one
 * interpreter, finding the dependencies missing, and installing into it --
 * which is how a Windows runner with everything already installed ended up
 * trying to build wheels from source.
 *
 * PATH first is therefore correct on every platform: it is what a virtualenv
 * activates, what CI configures, and what the rest of the toolchain uses. The
 * Store stub needs no special case, because it exits non-zero and `tryRun`
 * already discards anything that fails.
 */
const PYTHON_CANDIDATES =
  process.platform === "win32"
    ? [
        ["python", []],
        ["python3", []],
        ["py", ["-3"]],
      ]
    : [
        ["python3", []],
        ["python", []],
      ];

export function findPython() {
  const rejected = [];
  for (const [command, prefix] of PYTHON_CANDIDATES) {
    const output = tryRun(command, [...prefix, "--version"]);
    if (!output) continue;
    const version = parseVersion(output);
    if (!version) continue;
    const text = version.join(".");
    if (atLeast(text, PYTHON_MIN)) {
      return { command, prefix, version: text, ok: true };
    }
    rejected.push(`${command} (${text})`);
  }
  return { ok: false, rejected };
}

/**
 * Detect a *working* Docker, not merely an installed binary.
 *
 * `docker --version` succeeds while the daemon is down -- that exact trap cost
 * real time during this project's live-mode verification -- so this asks the
 * daemon for its version instead, and treats a hang as unavailable.
 */
export function detectDocker() {
  const version = tryRun("docker", ["info", "--format", "{{.ServerVersion}}"], {
    timeout: 12_000,
  });
  if (version) return { available: true, version: version.split("\n").pop().trim() };
  const installed = tryRun("docker", ["--version"], { timeout: 8_000 });
  return { available: false, installed: Boolean(installed) };
}
