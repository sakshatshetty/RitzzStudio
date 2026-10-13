import { spawn } from "node:child_process";
import { once } from "node:events";
import { setTimeout as delay } from "node:timers/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const studioPath = join(root, "dist", "studio.js");
const generatorPath = join(root, "scripts", "ritzz-generate-flow-images.mjs");
const port = process.env.FLOW_MCP_PORT ?? "8787";
const healthUrl = `http://127.0.0.1:${port}/api/health`;
const args = process.argv.slice(2);
const skipStudio = args.some((arg) => ["--dry-run", "--help", "-h"].includes(arg));
const activeChildren = new Set();
let interrupted = false;

function startNode(script, childArgs = []) {
  const child = spawn(process.execPath, [script, ...childArgs], {
    cwd: root,
    stdio: "inherit",
  });
  activeChildren.add(child);
  child.once("close", () => activeChildren.delete(child));
  return child;
}

function runNode(script, childArgs = []) {
  const child = startNode(script, childArgs);
  return new Promise((resolve, reject) => {
    child.once("error", reject);
    child.once("exit", (code, signal) => resolve({ code, signal }));
  });
}

async function flowIsReady() {
  try {
    const response = await fetch(healthUrl, { signal: AbortSignal.timeout(1500) });
    if (!response.ok) return false;
    const body = await response.json();
    return body.name === "flow-mcp";
  } catch {
    return false;
  }
}

async function waitForFlow(child) {
  const deadline = Date.now() + 120_000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) {
      if (await flowIsReady()) return false;
      throw new Error(`Flow Studio exited before becoming ready (exit code ${child.exitCode}).`);
    }
    if (await flowIsReady()) return true;
    await delay(1000);
  }
  throw new Error("Flow Studio did not become ready within 120 seconds.");
}

async function stopChild(child) {
  if (!child || child.exitCode !== null || child.signalCode !== null) return;
  child.kill();
  await Promise.race([once(child, "exit"), delay(3000)]);
  if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
}

function stopActiveChildren() {
  interrupted = true;
  for (const child of activeChildren) {
    if (child.exitCode === null && child.signalCode === null) child.kill();
  }
}

for (const signal of ["SIGINT", "SIGBREAK", "SIGTERM"]) {
  process.on(signal, stopActiveChildren);
}

let ownedStudio;
let exitCode = 1;
try {
  if (!skipStudio) {
    if (await flowIsReady()) {
      console.log("Using an existing Flow MCP service; this launcher will not stop a service it did not start.");
    } else {
      console.log("Starting Flow Studio in this command session.");
      ownedStudio = startNode(studioPath);
      if (!(await waitForFlow(ownedStudio))) {
        console.log("An existing Flow MCP service became available; leaving its lifecycle to its owner.");
        ownedStudio = undefined;
      }
    }
  }

  const result = await runNode(generatorPath, args);
  exitCode = interrupted ? 130 : result.code ?? 1;
  if (result.signal) {
    console.error(`Image generation ended after receiving ${result.signal}.`);
  }
} catch (error) {
  console.error(`RITZZ Flow launcher failed: ${error instanceof Error ? error.message : String(error)}`);
} finally {
  if (ownedStudio) {
    console.log("Stopping the Flow Studio service started by this launcher.");
    await stopChild(ownedStudio);
  }
  for (const signal of ["SIGINT", "SIGBREAK", "SIGTERM"]) {
    process.removeListener(signal, stopActiveChildren);
  }
}

process.exitCode = exitCode;
