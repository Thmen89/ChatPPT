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
import { randomUUID } from "node:crypto";
import {
  accessSync,
  chmodSync,
  chownSync,
  closeSync,
  constants as fsConstants,
  copyFileSync,
  existsSync,
  fsyncSync,
  lstatSync,
  mkdirSync,
  openSync,
  readdirSync,
  readFileSync,
  renameSync,
  statSync,
  unlinkSync,
  writeFileSync,
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
const canChangeKeys = process.env.CAN_CHANGE_KEYS !== "false";

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

const userConfigPath = join(dataDir, "userConfig.json");
const userConfigBackupPath = `${userConfigPath}.bak`;

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

// --------------------------------------------------------------------------- userConfig.json (legacy)

const readJsonConfig = (filePath) => {
  try {
    if (!existsSync(filePath)) {
      return undefined;
    }
    const raw = readFileSync(filePath, "utf8").trim();
    if (!raw) {
      return {};
    }
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? parsed
      : undefined;
  } catch {
    return undefined;
  }
};

const readUserConfig = () =>
  readJsonConfig(userConfigPath) || readJsonConfig(userConfigBackupPath) || {};

const copyUserConfigBackup = () => {
  try {
    if (readJsonConfig(userConfigPath)) {
      copyFileSync(userConfigPath, userConfigBackupPath);
      chmodSync(userConfigBackupPath, 0o600);
    }
  } catch (error) {
    warn(`Failed to update user config backup: ${error}`);
  }
};

const writeUserConfig = (config) => {
  copyUserConfigBackup();
  const tempPath = `${userConfigPath}.${process.pid}.${Date.now()}.${randomUUID()}.tmp`;
  const fd = openSync(tempPath, "w", 0o600);
  try {
    writeFileSync(fd, JSON.stringify(config), "utf8");
    fsyncSync(fd);
  } finally {
    closeSync(fd);
  }
  try {
    renameSync(tempPath, userConfigPath);
    if (!existsSync(userConfigBackupPath)) {
      copyUserConfigBackup();
    }
  } catch (error) {
    try {
      unlinkSync(tempPath);
    } catch {
      // Best-effort cleanup.
    }
    throw error;
  }
};

// Mirrors provider env vars into userConfig.json, which the settings screen edits.
// TODO(customisation workstream): delete once settings live in chatppt.toml only.
const setupUserConfigFromEnv = () => {
  let existingConfig = readUserConfig();

  if (!["ollama", "openai", "google", "vertex", "azure", "bedrock", "openrouter", "fireworks", "together", "cerebras", "anthropic", "litellm", "lmstudio", "custom", "codex"].includes(existingConfig.LLM)) {
    existingConfig.LLM = undefined;
  }

  const envValue = (key) => {
    const value = process.env[key];
    return value === undefined || value === "" ? undefined : value;
  };

  const configValue = (key) => envValue(key) ?? existingConfig[key];

  const parseBooleanLike = (value) => {
    if (typeof value === "boolean") {
      return value;
    }
    if (typeof value !== "string") {
      return undefined;
    }

    const normalized = value.trim().toLowerCase();
    if (["1", "true", "yes", "on"].includes(normalized)) {
      return true;
    }
    if (["0", "false", "no", "off"].includes(normalized)) {
      return false;
    }
    return undefined;
  };

  const normalizeImageConfig = (config) => {
    const parsedDisableImageGeneration = parseBooleanLike(
      config.DISABLE_IMAGE_GENERATION
    );
    if (parsedDisableImageGeneration !== undefined) {
      config.DISABLE_IMAGE_GENERATION = parsedDisableImageGeneration;
    }

    if (config.DISABLE_IMAGE_GENERATION || config.IMAGE_PROVIDER) {
      return config;
    }

    if (
      config.OPENAI_COMPAT_IMAGE_BASE_URL &&
      config.OPENAI_COMPAT_IMAGE_API_KEY &&
      config.OPENAI_COMPAT_IMAGE_MODEL
    ) {
      config.IMAGE_PROVIDER = "openai_compatible";
    } else if (config.OPEN_WEBUI_IMAGE_URL) {
      config.IMAGE_PROVIDER = "open_webui";
    } else if (config.COMFYUI_URL) {
      config.IMAGE_PROVIDER = "comfyui";
    } else if (config.PEXELS_API_KEY) {
      config.IMAGE_PROVIDER = "pexels";
    } else if (config.PIXABAY_API_KEY) {
      config.IMAGE_PROVIDER = "pixabay";
    } else if (config.LLM === "openai" && config.OPENAI_API_KEY) {
      config.IMAGE_PROVIDER = "gpt-image-1.5";
      config.GPT_IMAGE_1_5_QUALITY = config.GPT_IMAGE_1_5_QUALITY || "medium";
    } else if (config.LLM === "google" && config.GOOGLE_API_KEY) {
      config.IMAGE_PROVIDER = "gemini_flash";
    } else {
      config.DISABLE_IMAGE_GENERATION = true;
    }

    return config;
  };

  const userConfig = {
    LLM: process.env.LLM || existingConfig.LLM,
    OPENAI_API_KEY: process.env.OPENAI_API_KEY || existingConfig.OPENAI_API_KEY,
    OPENAI_MODEL: process.env.OPENAI_MODEL || existingConfig.OPENAI_MODEL,
    GOOGLE_API_KEY: process.env.GOOGLE_API_KEY || existingConfig.GOOGLE_API_KEY,
    GOOGLE_MODEL: process.env.GOOGLE_MODEL || existingConfig.GOOGLE_MODEL,
    VERTEX_API_KEY: process.env.VERTEX_API_KEY || existingConfig.VERTEX_API_KEY,
    VERTEX_MODEL: process.env.VERTEX_MODEL || existingConfig.VERTEX_MODEL,
    VERTEX_PROJECT: process.env.VERTEX_PROJECT || existingConfig.VERTEX_PROJECT,
    VERTEX_LOCATION: process.env.VERTEX_LOCATION || existingConfig.VERTEX_LOCATION,
    VERTEX_BASE_URL: process.env.VERTEX_BASE_URL || existingConfig.VERTEX_BASE_URL,
    AZURE_OPENAI_API_KEY:
      process.env.AZURE_OPENAI_API_KEY || existingConfig.AZURE_OPENAI_API_KEY,
    AZURE_OPENAI_MODEL:
      process.env.AZURE_OPENAI_MODEL || existingConfig.AZURE_OPENAI_MODEL,
    AZURE_OPENAI_ENDPOINT:
      process.env.AZURE_OPENAI_ENDPOINT || existingConfig.AZURE_OPENAI_ENDPOINT,
    AZURE_OPENAI_BASE_URL:
      process.env.AZURE_OPENAI_BASE_URL || existingConfig.AZURE_OPENAI_BASE_URL,
    AZURE_OPENAI_API_VERSION:
      process.env.AZURE_OPENAI_API_VERSION || existingConfig.AZURE_OPENAI_API_VERSION,
    AZURE_OPENAI_DEPLOYMENT:
      process.env.AZURE_OPENAI_DEPLOYMENT || existingConfig.AZURE_OPENAI_DEPLOYMENT,
    BEDROCK_REGION: process.env.BEDROCK_REGION || existingConfig.BEDROCK_REGION,
    BEDROCK_API_KEY: process.env.BEDROCK_API_KEY || existingConfig.BEDROCK_API_KEY,
    BEDROCK_AWS_ACCESS_KEY_ID:
      process.env.BEDROCK_AWS_ACCESS_KEY_ID || existingConfig.BEDROCK_AWS_ACCESS_KEY_ID,
    BEDROCK_AWS_SECRET_ACCESS_KEY:
      process.env.BEDROCK_AWS_SECRET_ACCESS_KEY || existingConfig.BEDROCK_AWS_SECRET_ACCESS_KEY,
    BEDROCK_AWS_SESSION_TOKEN:
      process.env.BEDROCK_AWS_SESSION_TOKEN || existingConfig.BEDROCK_AWS_SESSION_TOKEN,
    BEDROCK_PROFILE_NAME:
      process.env.BEDROCK_PROFILE_NAME || existingConfig.BEDROCK_PROFILE_NAME,
    BEDROCK_MODEL: process.env.BEDROCK_MODEL || existingConfig.BEDROCK_MODEL,
    FIREWORKS_API_KEY: process.env.FIREWORKS_API_KEY || existingConfig.FIREWORKS_API_KEY,
    FIREWORKS_MODEL: process.env.FIREWORKS_MODEL || existingConfig.FIREWORKS_MODEL,
    FIREWORKS_BASE_URL: process.env.FIREWORKS_BASE_URL || existingConfig.FIREWORKS_BASE_URL,
    TOGETHER_API_KEY: process.env.TOGETHER_API_KEY || existingConfig.TOGETHER_API_KEY,
    TOGETHER_MODEL: process.env.TOGETHER_MODEL || existingConfig.TOGETHER_MODEL,
    TOGETHER_BASE_URL: process.env.TOGETHER_BASE_URL || existingConfig.TOGETHER_BASE_URL,
    OLLAMA_URL: process.env.OLLAMA_URL || existingConfig.OLLAMA_URL,
    OLLAMA_MODEL: process.env.OLLAMA_MODEL || existingConfig.OLLAMA_MODEL,
    ANTHROPIC_API_KEY:
      process.env.ANTHROPIC_API_KEY || existingConfig.ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL:
      process.env.ANTHROPIC_MODEL || existingConfig.ANTHROPIC_MODEL,
    CUSTOM_LLM_URL: process.env.CUSTOM_LLM_URL || existingConfig.CUSTOM_LLM_URL,
    CUSTOM_LLM_API_KEY:
      process.env.CUSTOM_LLM_API_KEY || existingConfig.CUSTOM_LLM_API_KEY,
    CUSTOM_MODEL: process.env.CUSTOM_MODEL || existingConfig.CUSTOM_MODEL,
    LITELLM_BASE_URL: process.env.LITELLM_BASE_URL || existingConfig.LITELLM_BASE_URL,
    LITELLM_API_KEY: process.env.LITELLM_API_KEY || existingConfig.LITELLM_API_KEY,
    LITELLM_MODEL: process.env.LITELLM_MODEL || existingConfig.LITELLM_MODEL,
    LMSTUDIO_BASE_URL: process.env.LMSTUDIO_BASE_URL || existingConfig.LMSTUDIO_BASE_URL,
    LMSTUDIO_API_KEY: process.env.LMSTUDIO_API_KEY || existingConfig.LMSTUDIO_API_KEY,
    LMSTUDIO_MODEL: process.env.LMSTUDIO_MODEL || existingConfig.LMSTUDIO_MODEL,
    PEXELS_API_KEY: process.env.PEXELS_API_KEY || existingConfig.PEXELS_API_KEY,
    PIXABAY_API_KEY:
      process.env.PIXABAY_API_KEY || existingConfig.PIXABAY_API_KEY,
    IMAGE_PROVIDER: process.env.IMAGE_PROVIDER || existingConfig.IMAGE_PROVIDER,
    DISABLE_IMAGE_GENERATION:
      configValue("DISABLE_IMAGE_GENERATION") ?? existingConfig.DISABLE_IMAGE_GENERATION,
    DISABLE_THINKING:
      process.env.DISABLE_THINKING || existingConfig.DISABLE_THINKING,
    EXTENDED_REASONING:
      process.env.EXTENDED_REASONING || existingConfig.EXTENDED_REASONING,
    WEB_GROUNDING: process.env.WEB_GROUNDING || existingConfig.WEB_GROUNDING,
    USE_CUSTOM_URL: process.env.USE_CUSTOM_URL || existingConfig.USE_CUSTOM_URL,
    COMFYUI_URL: process.env.COMFYUI_URL || existingConfig.COMFYUI_URL,
    COMFYUI_WORKFLOW:
      process.env.COMFYUI_WORKFLOW || existingConfig.COMFYUI_WORKFLOW,
    DALL_E_3_QUALITY:
      process.env.DALL_E_3_QUALITY || existingConfig.DALL_E_3_QUALITY,
    GPT_IMAGE_1_5_QUALITY:
      process.env.GPT_IMAGE_1_5_QUALITY || existingConfig.GPT_IMAGE_1_5_QUALITY,
    CODEX_MODEL: process.env.CODEX_MODEL || existingConfig.CODEX_MODEL,
    CODEX_ACCESS_TOKEN: existingConfig.CODEX_ACCESS_TOKEN,
    CODEX_REFRESH_TOKEN: existingConfig.CODEX_REFRESH_TOKEN,
    CODEX_TOKEN_EXPIRES: existingConfig.CODEX_TOKEN_EXPIRES,
    CODEX_ACCOUNT_ID: existingConfig.CODEX_ACCOUNT_ID,
    AUTH_USERNAME: existingConfig.AUTH_USERNAME,
    AUTH_PASSWORD_HASH: existingConfig.AUTH_PASSWORD_HASH,
    AUTH_SECRET_KEY: existingConfig.AUTH_SECRET_KEY,
  };

  writeUserConfig(normalizeImageConfig(userConfig));
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
  if (canChangeKeys) {
    setupUserConfigFromEnv();
  }

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
