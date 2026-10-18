/* ChatPPT container entrypoint (PID 1).
 *
 * One public port, two runtimes, no reverse proxy:
 *
 *   :5000 (PORT)  Next.js, served from this very process. It renders the UI and forwards
 *                 /api/v1, /app_data, /static, /mcp and /docs to FastAPI (next.config.mjs).
 *   127.0.0.1:8000 FastAPI (uvicorn), a child process. MCP is mounted inside it at /mcp.
 *
 * Nothing is downloaded or installed here. When started as root (the image default) it
 * makes the data folder writable for the `chatppt` user and drops to that user before
 * anything else runs.
 */

import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { spawn } from "node:child_process";
import {
  accessSync,
  chownSync,
  constants as fsConstants,
  existsSync,
  lstatSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  statSync,
} from "node:fs";
import { printStartupBanner } from "./scripts/chatppt-banner.mjs";

const startedAt = Date.now();
process.umask(0o022);

const __dirname = dirname(fileURLToPath(import.meta.url));
const fastapiDir = join(__dirname, "servers/fastapi");
const nextjsDir = join(__dirname, "servers/nextjs");
const nextjsStandaloneServer = join(nextjsDir, "server.js");

const args = process.argv.slice(2);
const isDev = args.includes("--dev") || args.includes("-d");

const publicPort = Number.parseInt(process.env.PORT || "5000", 10);
/** Fixed: next.config.mjs rewrites point here at build time. */
const fastapiPort = 8000;
const APP_USER = "chatppt";

const log = (msg) => console.log(`[chatppt] ${msg}`);
const warn = (msg) => console.warn(`[chatppt] ${msg}`);
const fail = (msg) => {
  console.error(`[chatppt] ${msg}`);
  process.exit(1);
};

const hasEntries = (dir) => {
  try {
    return readdirSync(dir).some((name) => name !== "lost+found");
  } catch {
    return false;
  }
};

/** /data by default. A volume still mounted at the old Presenton path /app_data keeps working. */
const resolveDataDir = () => {
  const configured =
    process.env.CHATPPT_SERVER__DATA_DIR?.trim() || process.env.APP_DATA_DIRECTORY?.trim();
  if (configured) {
    return configured;
  }
  if (hasEntries("/app_data") && !hasEntries("/data")) {
    warn(
      "Using data found in /app_data (the old Presenton path). It keeps working; to switch, " +
        "mount the same folder at /data instead (-v ./chatppt:/data)."
    );
    return "/app_data";
  }
  return "/data";
};

// --------------------------------------------------------------------------- user

const lookupUser = (name) => {
  try {
    const line = readFileSync("/etc/passwd", "utf8")
      .split("\n")
      .find((l) => l.startsWith(`${name}:`));
    if (!line) return undefined;
    const [, , uid, gid, , home] = line.split(":");
    return { uid: Number(uid), gid: Number(gid), home };
  } catch {
    return undefined;
  }
};

const chownTree = (path, uid, gid) => {
  const st = lstatSync(path);
  if (st.isSymbolicLink()) return;
  if (st.uid !== uid || st.gid !== gid) chownSync(path, uid, gid);
  if (st.isDirectory()) {
    for (const name of readdirSync(path)) chownTree(join(path, name), uid, gid);
  }
};

/** Root in the image: hand the data folder to the app user, then become that user. */
const dropPrivileges = (dataDir) => {
  if (typeof process.getuid !== "function" || process.getuid() !== 0) return;
  if (process.env.CHATPPT_RUN_AS_ROOT === "true") return;
  const user = lookupUser(APP_USER);
  if (!user) return; // not the container image (no such user): run as is
  mkdirSync(dataDir, { recursive: true });
  if (statSync(dataDir).uid !== user.uid) {
    log(`Giving ${dataDir} to user ${APP_USER} (uid ${user.uid}); this happens once.`);
    chownTree(dataDir, user.uid, user.gid);
  }
  process.initgroups(APP_USER, user.gid);
  process.setgid(user.gid);
  process.setuid(user.uid);
  process.env.HOME = user.home;
  process.env.USER = APP_USER;
};

const ensureWritable = (dir) => {
  try {
    mkdirSync(dir, { recursive: true });
    accessSync(dir, fsConstants.W_OK);
  } catch (err) {
    const uid = typeof process.getuid === "function" ? process.getuid() : "?";
    fail(
      `The data folder ${dir} is not writable by uid ${uid} (${err.code || err.message}). ` +
        `Fix the host folder's owner (e.g. sudo chown -R ${uid} ./chatppt) or run the container ` +
        "without --user so it can fix it itself."
    );
  }
};

// --------------------------------------------------------------------------- environment

const dataDir = resolveDataDir();
dropPrivileges(dataDir);
ensureWritable(dataDir);
for (const name of ["exports", "images", "uploads", "fonts", "pptx-to-html"]) {
  mkdirSync(join(dataDir, name), { recursive: true });
}

// Only Codex sign-in tokens still live here; settings are chatppt.toml + CHATPPT_* env.
const userConfigPath = join(dataDir, "userConfig.json");

// Upstream code reads these names; setting the CHATPPT_ one too keeps settings explicit
// (no "legacy variable" warning) and every process on the same folder.
process.env.CHATPPT_SERVER__DATA_DIR = dataDir;
process.env.APP_DATA_DIRECTORY = dataDir;
process.env.USER_CONFIG_PATH = userConfigPath;
process.env.TEMP_DIRECTORY ||= "/tmp/chatppt";
// Next.js → FastAPI over loopback, and FastAPI / the exporter → Next.js the same way.
process.env.FAST_API_INTERNAL_URL ||= `http://127.0.0.1:${fastapiPort}`;
process.env.CHATPPT_NEXTJS_URL ||= `http://127.0.0.1:${publicPort}`;
process.env.NEXT_MANUAL_SIG_HANDLE = "true"; // this file handles SIGTERM for both servers
process.env.NEXT_TELEMETRY_DISABLED = "1";

if (["1", "true", "yes", "on"].includes(String(process.env.START_OLLAMA).toLowerCase())) {
  warn("START_OLLAMA is not supported (nothing is installed at runtime). Run Ollama separately and set OLLAMA_URL.");
}

// --------------------------------------------------------------------------- export runtime

/** Baked into the image at build time; this only reports, it never downloads. */
const checkExportRuntime = () => {
  if (String(process.env.CHATPPT_EXPORT_ENGINE || "").trim().toLowerCase() !== "bundle") {
    // The built-in exporter needs only a Chromium (the Next.js server drives it).
    const chromium = process.env.CHATPPT_CHROMIUM_PATH?.trim() || process.env.PUPPETEER_EXECUTABLE_PATH?.trim();
    if (!chromium || !existsSync(chromium)) {
      warn(
        `PPTX/PDF export is unavailable: no Chromium at PUPPETEER_EXECUTABLE_PATH (${chromium || "unset"}).`
      );
    }
    return;
  }
  const root =
    process.env.EXPORT_RUNTIME_DIR?.trim() ||
    process.env.EXPORT_PACKAGE_ROOT?.trim() ||
    join(__dirname, "presentation-export");
  const hasEntry = existsSync(join(root, "index.cjs")) || existsSync(join(root, "index.js"));
  const converter = process.env.BUILT_PYTHON_MODULE_PATH?.trim() || join(root, "py", "convert-linux-x64");
  if (!hasEntry || !existsSync(converter)) {
    warn(
      `PPTX/PDF export is unavailable: no export runtime at ${root}. ` +
        (isDev
          ? "Run `npm run sync:presentation-export` once."
          : "This image was built without it (e.g. arm64); `chatppt doctor` explains.")
    );
  }
};

// --------------------------------------------------------------------------- processes

const children = new Set();

const stopChildren = (signal = "SIGTERM") => {
  for (const child of children) {
    if (child.exitCode === null && child.signalCode === null) child.kill(signal);
  }
};

const waitForHttp = async (url, timeoutMs = 120_000) => {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(url, { signal: AbortSignal.timeout(1000) });
      if (res.ok) return true;
    } catch {
      // not up yet
    }
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  return false;
};

const startFastApi = () => {
  const child = spawn(
    process.env.CHATPPT_PYTHON || "python",
    ["server.py", "--port", String(fastapiPort), "--reload", isDev ? "true" : "false"],
    { cwd: fastapiDir, stdio: "inherit", env: process.env }
  );
  children.add(child);
  child.on("error", (err) => fail(`FastAPI could not start: ${err.message}`));
  child.on("exit", (code, signal) => {
    children.delete(child);
    if (!shuttingDown) {
      console.error(`[chatppt] FastAPI exited (${signal || code}); stopping.`);
      shutdown(typeof code === "number" && code !== 0 ? code : 1);
    }
  });
  return child;
};

/** Production: the standalone Next.js server runs inside this process (one Node runtime). */
const startNextJs = async () => {
  if (isDev || !existsSync(nextjsStandaloneServer)) {
    const child = spawn(
      "npm",
      ["run", isDev ? "dev" : "start", "--", "-H", "0.0.0.0", "-p", String(publicPort)],
      { cwd: nextjsDir, stdio: "inherit", env: process.env }
    );
    children.add(child);
    child.on("exit", (code) => {
      children.delete(child);
      if (!shuttingDown) shutdown(typeof code === "number" && code !== 0 ? code : 1);
    });
    return;
  }
  process.env.PORT = String(publicPort);
  // Docker sets HOSTNAME to the container id; Next.js would bind to that, not all interfaces.
  process.env.HOSTNAME = "0.0.0.0";
  await import(pathToFileURL(nextjsStandaloneServer).href);
};

let shuttingDown = false;
const shutdown = (code = 0) => {
  if (shuttingDown) return;
  shuttingDown = true;
  stopChildren("SIGTERM");
  const timer = setTimeout(() => {
    stopChildren("SIGKILL");
    process.exit(code);
  }, 5000);
  timer.unref();
  const check = setInterval(() => {
    if (children.size === 0) {
      clearInterval(check);
      process.exit(code);
    }
  }, 50);
};

process.on("SIGTERM", () => shutdown(0));
process.on("SIGINT", () => shutdown(0));
process.on("exit", () => stopChildren("SIGKILL"));

const main = async () => {
  checkExportRuntime();

  // FastAPI (Python imports) is the slow one: start it first, then Next.js alongside.
  startFastApi();
  await startNextJs();

  const ready = await waitForHttp(`http://127.0.0.1:${publicPort}/healthz`);
  if (!ready) {
    fail("ChatPPT did not become ready within 120 s; see the log lines above.");
  }
  printStartupBanner({ port: publicPort, dataDir, startupMs: Date.now() - startedAt });
};

main().catch((err) => {
  console.error(err);
  shutdown(1);
});
