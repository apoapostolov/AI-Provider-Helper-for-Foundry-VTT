#!/usr/bin/env node
"use strict";

/**
 * npm entry for the AI Provider Library helper.
 *
 * Phase A of the helper split: locate Python 3.11+, create a venv next to
 * the package backend on first run, install requirements, then exec uvicorn
 * plus the 8091 control server as a foreground pair. GMs keep the zip; this
 * wrapper serves technical users and CI.
 *
 * Usage: npx ai-provider-helper [--port 8090] [--ctl-port 8091] [--hosted]
 */

const { spawn, spawnSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const BACKEND = path.join(__dirname, "..", "backend");
const VENV = path.join(BACKEND, ".venv");
const HOSTED_ORIGINS = [
  "https://*.forge-vtt.com",
  "https://*.moltenhosting.com",
  "https://*.foundryserver.com",
];

function die(message) {
  process.stderr.write(`ai-provider-helper: ${message}\n`);
  process.exit(1);
}

function parseArgs(argv) {
  const out = { port: 8090, ctlPort: 8091, hosted: false, setup: false };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--port") out.port = Number(argv[++i]);
    else if (arg === "--ctl-port") out.ctlPort = Number(argv[++i]);
    else if (arg === "--hosted") out.hosted = true;
    else if (arg === "--setup") out.setup = true;
    else if (arg === "--help" || arg === "-h") {
      console.log("Usage: npx ai-provider-helper [--port 8090] [--ctl-port 8091] [--hosted] [--setup]");
      process.exit(0);
    } else die(`unknown argument ${arg}`);
  }
  if (!Number.isInteger(out.port) || out.port <= 0) die("--port needs a positive integer");
  if (!Number.isInteger(out.ctlPort) || out.ctlPort <= 0) die("--ctl-port needs a positive integer");
  return out;
}

function findPython() {
  const candidates = [];
  if (process.env.APL_PYTHON) candidates.push(process.env.APL_PYTHON);
  const uvPy = path.join(os.homedir(), ".local", "share", "uv", "python");
  for (const base of [uvPy, path.join(os.homedir(), "AppData", "Roaming", "uv", "python")]) {
    try {
      for (const entry of fs.readdirSync(base)) {
        const candidate = path.join(base, entry, os.platform() === "win32" ? "python.exe" : "bin", "python3");
        candidates.push(candidate);
      }
    } catch {}
  }
  candidates.push("python3");
  candidates.push("python");
  for (const candidate of candidates) {
    const probe = spawnSync(candidate, ["-c", "import sys; exit(0 if sys.version_info >= (3, 11) else 1)"], {
      stdio: "ignore",
    });
    if (probe.status === 0) return candidate;
  }
  return null;
}

function venvPython() {
  return os.platform() === "win32"
    ? path.join(VENV, "Scripts", "python.exe")
    : path.join(VENV, "bin", "python");
}

function ensureVenv(python) {
  if (fs.existsSync(venvPython())) return;
  console.log("ai-provider-helper: first run, creating venv and installing requirements...");
  const create = spawnSync(python, ["-m", "venv", VENV], { stdio: "inherit" });
  if (create.status !== 0) die("venv creation failed");
  const install = spawnSync(venvPython(), ["-m", "pip", "install", "-r", path.join(BACKEND, "requirements.txt")], {
    stdio: "inherit",
  });
  if (install.status !== 0) die("pip install failed");
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  const python = findPython();
  if (!python) {
    die("no Python 3.11+ found. Install Python, or set APL_PYTHON to its full path.");
  }
  ensureVenv(python);

  const cache = path.join(os.homedir(), ".cache", "ai-provider-helper");
  fs.mkdirSync(cache, { recursive: true });
  const env = {
    ...process.env,
    APL_HOST: "127.0.0.1",
    APL_PORT: String(args.port),
    APL_CTL_HOST: "127.0.0.1",
    APL_CTL_PORT: String(args.ctlPort),
    APL_CTL_BACKEND: "child",
    APL_CACHE: cache,
  };
  if (args.hosted) env.APL_CORS_ORIGINS = HOSTED_ORIGINS.join(",");

  console.log("AI Helper (npm)");
  console.log(`  app  http://127.0.0.1:${args.port}/health`);
  console.log(`  ctl  http://127.0.0.1:${args.ctlPort}/status`);
  console.log(`  vault ${cache}`);
  if (args.hosted) console.log("  hosted Foundry: keep Endpoint Host at 127.0.0.1");
  console.log("  press Ctrl+C to stop");

  // Same shape companion/launch.py runs: 8090 app plus 8091 control, in this
  // terminal, no daemon. Ctrl+C stops both.
  const root = BACKEND;
  const app = spawn(venvPython(), ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", String(args.port), "--timeout-graceful-shutdown", "3"], {
    cwd: root,
    env,
    stdio: "inherit",
  });
  const ctl = spawn(venvPython(), ["scripts/ctl_server.py"], { cwd: root, env, stdio: "inherit" });
  const stop = () => {
    app.kill();
    ctl.kill();
  };
  process.on("SIGINT", stop);
  process.on("SIGTERM", stop);
  app.on("exit", stop);
  ctl.on("exit", stop);
}

main();
