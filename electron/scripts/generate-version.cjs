const fs = require("fs");
const path = require("path");

const electronRoot = path.join(__dirname, "..");
const pkg = JSON.parse(
  fs.readFileSync(path.join(electronRoot, "package.json"), "utf8"),
);
let existing = {};
try {
  existing = JSON.parse(
    fs.readFileSync(path.join(electronRoot, "version.json"), "utf8"),
  );
} catch (_) {}

const version = pkg.version;

const update = {
  version,
  message: process.env.UPDATE_MESSAGE || existing.message || "",
  downloads: {
    linux: `https://github.com/Thmen89/ChatPPT/releases/download/electron-v${version}/ChatPPT-${version}.deb`,
    mac: `https://github.com/Thmen89/ChatPPT/releases/download/electron-v${version}/ChatPPT-${version}.dmg`,
    windows: `https://github.com/Thmen89/ChatPPT/releases/download/electron-v${version}/ChatPPT-${version}.exe`,
  },
};

fs.writeFileSync(
  path.join(electronRoot, "version.json"),
  JSON.stringify(update, null, 2),
);

console.log("version.json generated");
