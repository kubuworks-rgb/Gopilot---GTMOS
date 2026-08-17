/**
 * Dependency installation, process supervision, and readiness checking.
 *
 * "Ready" here means the server answered an HTTP request, not that a process
 * was spawned. A spawned process that is still importing modules, or that died
 * three seconds later, is not a running application, and telling someone to
 * open a URL that is not serving yet is the fastest way to look broken.
 */

import { spawn, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { NPM, NPM_NEEDS_SHELL } from "./prereqs.mjs";

export const API_URL = "http://127.0.0.1:8000/api/v1/bootstrap";
export const WEB_URL = "http://localhost:3000";

const REQUIREMENTS = join("apps", "api", "requirements-dev.txt");

export function nodeDepsInstalled(root) {
  // .package-lock.json inside node_modules is written on a completed install,
  // so it is a better signal than the directory merely existing.
  return existsSync(join(root, "node_modules", ".package-lock.json"));
}

export function installNodeDeps(root) {
  console.log("Installing JavaScript dependencies (npm install)...");
  const result = spawnSync(NPM, ["install"], {
    cwd: root,
    stdio: "inherit",
    shell: NPM_NEEDS_SHELL,
    windowsHide: true,
  });
  return result.status === 0;
}

export function pythonDepsInstalled(root, python) {
  const result = spawnSync(
    python.command,
    [...python.prefix, "-c", "import fastapi, uvicorn, pydantic"],
    { cwd: root, encoding: "utf8", timeout: 30_000, windowsHide: true },
  );
  return result.status === 0;
}

export function installPythonDeps(root, python) {
  console.log(`Installing Python dependencies (pip install -r ${REQUIREMENTS})...`);
  const result = spawnSync(
    python.command,
    [...python.prefix, "-m", "pip", "install", "-r", REQUIREMENTS],
    { cwd: root, stdio: "inherit", windowsHide: true },
  );
  if (result.status === 0) return true;

  // The requirements pin `agent-reach` to a GitHub archive URL, and GitHub
  // rate-limits (HTTP 429) often enough that a first-time install can fail on
  // it alone. It is an external CLI used only for the research gateway's
  // capability report -- the gateway does not even start in demo mode -- so if
  // everything the app actually imports is present, that is not a reason to
  // refuse to start.
  if (pythonDepsInstalled(root, python)) {
    console.warn(
      [
        "",
        "  Some optional dependencies did not install (see above), but every",
        "  package the application imports is present, so setup is continuing.",
        "",
        "  Most likely `agent-reach`, which installs from a GitHub URL that",
        "  rate-limits. It only affects the research gateway's capability",
        "  report in live mode. Demo mode does not use it at all.",
        "",
      ].join("\n"),
    );
    return true;
  }

  console.error(
    [
      "",
      "Python dependencies could not be installed.",
      "",
      "If the error above mentions an externally-managed environment, your OS",
      "protects its system Python. Create a virtual environment and re-run:",
      "",
      "  python -m venv .venv",
      process.platform === "win32"
        ? "  .venv\\Scripts\\activate"
        : "  source .venv/bin/activate",
      "  npx gopilot",
      "",
    ].join("\n"),
  );
  return false;
}

/** Bring up Postgres and Redis, and wait for Postgres to report healthy. */
export async function startDockerInfra(root) {
  const compose = join("deploy", "docker-compose.dev-infra.yml");
  console.log("Starting Postgres and Redis (docker compose)...");
  const up = spawnSync("docker", ["compose", "-f", compose, "up", "-d"], {
    cwd: root,
    stdio: "inherit",
    windowsHide: true,
  });
  if (up.status !== 0) {
    console.error(
      "\nDocker could not start the database. Is Docker Desktop running?\n" +
        "You can continue in Demo mode with:  npx gopilot --reconfigure\n",
    );
    return false;
  }
  for (let attempt = 0; attempt < 30; attempt += 1) {
    const health = spawnSync(
      "docker",
      ["inspect", "--format", "{{.State.Health.Status}}", "deploy-postgres-1"],
      { encoding: "utf8", windowsHide: true },
    );
    if ((health.stdout ?? "").trim() === "healthy") return true;
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  console.error("Postgres did not become healthy in time.");
  return false;
}

/** Apply migrations so a fresh database is usable. Live mode only. */
export function applyMigrations(root, python, env) {
  console.log("Applying database migrations...");
  const result = spawnSync(
    python.command,
    [...python.prefix, "-m", "alembic", "-c", join("apps", "api", "alembic.ini"), "upgrade", "head"],
    {
      cwd: root,
      stdio: "inherit",
      windowsHide: true,
      env: { ...process.env, ...env, PYTHONPATH: root },
    },
  );
  return result.status === 0;
}

export function startStack(root, mode, env) {
  return spawn(NPM, ["run", mode.script], {
    cwd: root,
    stdio: "inherit",
    shell: NPM_NEEDS_SHELL,
    windowsHide: true,
    env: { ...process.env, ...env, PYTHONPATH: root },
  });
}

async function responds(url) {
  try {
    // Any HTTP status proves the server is listening. Live mode legitimately
    // answers /bootstrap with 404 until a workspace exists, so requiring 200
    // would report a healthy stack as broken.
    await fetch(url, { signal: AbortSignal.timeout(2500) });
    return true;
  } catch {
    return false;
  }
}

export async function waitForReady({ timeoutMs = 180_000, child } = {}) {
  const deadline = Date.now() + timeoutMs;
  let api = false;
  let web = false;
  while (Date.now() < deadline) {
    if (child?.exitCode !== null && child?.exitCode !== undefined) return { ok: false, died: true };
    if (!api) api = await responds(API_URL);
    if (!web) web = await responds(WEB_URL);
    if (api && web) return { ok: true };
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  return { ok: false, api, web };
}

/** Best effort: a platform without a launcher must not fail the run. */
export function openBrowser(url) {
  const [command, args] =
    process.platform === "win32"
      ? ["cmd", ["/c", "start", "", url]]
      : process.platform === "darwin"
        ? ["open", [url]]
        : ["xdg-open", [url]];
  try {
    const child = spawn(command, args, { stdio: "ignore", detached: true, windowsHide: true });
    child.on("error", () => {});
    child.unref();
    return true;
  } catch {
    return false;
  }
}
