#!/usr/bin/env node
/**
 * `npx gopilot` -- the front door.
 *
 * Goes from a fresh clone to a browser tab in one command: checks the
 * prerequisites the project actually declares, installs what is missing, asks
 * at most three questions, starts the stack, and waits until it is genuinely
 * serving before saying so.
 *
 * This is an *additional* entry point. `npm install && npm run dev` remains the
 * documented manual path and is unchanged -- the CLI must never become a
 * prerequisite for the zero-config experience that already works.
 */

import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import process from "node:process";

import {
  NODE_MIN,
  NODE_RECOMMENDED,
  PYTHON_MIN,
  checkNode,
  detectDocker,
  findPython,
} from "./lib/prereqs.mjs";
import { MODES, interactive, readConfig, runWizard, writeConfig } from "./lib/wizard.mjs";
import {
  WEB_URL,
  applyMigrations,
  installNodeDeps,
  installPythonDeps,
  nodeDepsInstalled,
  openBrowser,
  pythonDepsInstalled,
  startDockerInfra,
  startStack,
  waitForReady,
} from "./lib/stack.mjs";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");

const HELP = `
  gopilot -- start GoPilot locally

  Usage
    npx gopilot [options]

  Options
    -y, --yes          Accept defaults (Demo mode). No prompts.
        --reconfigure  Re-run the setup wizard, ignoring saved answers.
        --no-open      Do not open a browser window.
    -h, --help         Show this message.

  First run asks up to three questions and remembers the answers in
  .env.gopilot (gitignored). Later runs start straight away.

  Demo mode needs no API keys, no Docker, and no database.
`;

function parseArgs(argv) {
  const flags = new Set(argv.slice(2));
  return {
    yes: flags.has("-y") || flags.has("--yes"),
    reconfigure: flags.has("--reconfigure"),
    noOpen: flags.has("--no-open"),
    help: flags.has("-h") || flags.has("--help"),
  };
}

function fail(message) {
  console.error(`\n${message}\n`);
  process.exit(1);
}

async function main() {
  const options = parseArgs(process.argv);
  if (options.help) {
    console.log(HELP);
    return;
  }

  console.log("\n  GoPilot\n  evidence-backed GTM research\n");

  // 1. Prerequisites -- report precisely, never work around silently.
  const node = checkNode();
  if (!node.ok) {
    fail(
      `Node ${node.version} is too old. GoPilot needs Node ${NODE_MIN} or newer\n` +
        `(Next.js 16 requires it). Install a current release from https://nodejs.org`,
    );
  }
  const python = findPython();
  if (!python.ok) {
    const seen = python.rejected?.length
      ? `\nFound, but too old: ${python.rejected.join(", ")}.`
      : "\nNo python3 interpreter was found on PATH.";
    fail(
      `GoPilot needs Python ${PYTHON_MIN} or newer (it uses StrEnum and ` +
        `datetime.UTC).${seen}\nInstall from https://python.org and re-run.`,
    );
  }
  console.log(`  Node ${node.version}  ·  Python ${python.version}`);
  if (!node.recommended) {
    console.log(
      `  note: Node ${NODE_RECOMMENDED}+ is needed for \`npm run test\`; the app itself runs fine.`,
    );
  }

  // 2. Decide the mode.
  const saved = options.reconfigure ? null : readConfig(ROOT);
  let mode;
  let extras = {};

  if (saved) {
    mode = saved.mode;
    extras = saved.env;
    console.log(`  mode: ${mode.label} (saved -- use --reconfigure to change)\n`);
  } else if (options.yes || !interactive()) {
    mode = MODES.demo;
    if (!options.yes) {
      console.log("  Not a terminal, so defaults were used instead of prompting.");
    }
    console.log(`  mode: ${mode.label} (default)\n`);
    writeConfig(ROOT, mode, {});
  } else {
    const docker = detectDocker();
    console.log(
      docker.available ? `  Docker ${docker.version} detected\n` : "",
    );
    const answers = await runWizard({ docker });
    mode = answers.mode;
    extras = answers.extras;
    writeConfig(ROOT, mode, extras);
    console.log("");
  }

  // 3. Dependencies -- install only what is missing.
  if (!nodeDepsInstalled(ROOT)) {
    if (!installNodeDeps(ROOT)) fail("npm install failed. See the output above.");
  } else {
    console.log("  JavaScript dependencies already installed.");
  }
  if (!pythonDepsInstalled(ROOT, python)) {
    if (!installPythonDeps(ROOT, python)) process.exit(1);
  } else {
    console.log("  Python dependencies already installed.");
  }

  // 4. Infrastructure, for the modes that need it.
  const env = {};
  for (const [key, value] of Object.entries(extras)) {
    if (key.startsWith("GOPILOT_") || key === "RESEARCH_MODE") continue;
    if (value) env[key] = value;
  }
  if (mode.docker) {
    const docker = detectDocker();
    if (!docker.available) {
      fail(
        "This configuration uses Docker for Postgres and Redis, but the Docker\n" +
          "daemon is not responding. Start Docker Desktop, or switch modes with:\n" +
          "  npx gopilot --reconfigure",
      );
    }
    if (!(await startDockerInfra(ROOT))) process.exit(1);
    if (!applyMigrations(ROOT, python, env)) {
      fail("Database migrations failed. See the output above.");
    }
  }

  // 5. Start, and wait until it is actually serving.
  console.log(`\n  Starting GoPilot in ${mode.label} mode...\n`);
  const child = startStack(ROOT, mode, env);
  let shuttingDown = false;
  const stop = () => {
    if (shuttingDown) return;
    shuttingDown = true;
    child.kill();
  };
  process.on("SIGINT", stop);
  process.on("SIGTERM", stop);
  child.on("exit", (code) => process.exit(code ?? 0));

  const ready = await waitForReady({ child });
  if (!ready.ok) {
    if (ready.died) return; // the child's own output already explained why
    console.error(
      `\n  Timed out waiting for the stack.` +
        `${ready.api ? "" : "\n  The API on :8000 never responded."}` +
        `${ready.web ? "" : "\n  The web app on :3000 never responded."}` +
        `\n  Check the log above; the ports may already be in use.\n`,
    );
    return;
  }

  const opened = options.noOpen ? false : openBrowser(WEB_URL);
  console.log(
    [
      "",
      "  ────────────────────────────────────────────",
      `  GoPilot is running   ${WEB_URL}`,
      "  ────────────────────────────────────────────",
      mode === MODES.demo
        ? "  Demo mode: fixture data, no API keys, nothing external."
        : "  Live mode: research fetches real company websites.",
      opened ? "  Opened in your browser." : `  Open ${WEB_URL} in your browser.`,
      "",
      "  Press Ctrl+C to stop.",
      "",
    ].join("\n"),
  );
}

main().catch((error) => {
  console.error(`\nUnexpected error: ${error?.message ?? error}\n`);
  process.exit(1);
});
