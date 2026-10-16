const builder = require("electron-builder")
const { execFileSync } = require("child_process")
const fs = require("fs")
const path = require("path")
const packageMetadata = require("./package.json")

// Build-time knobs are read as CHATPPT_*; the PRESENTON_* names are deprecated fallbacks.
const env = (name) => process.env[`CHATPPT_${name}`] || process.env[`PRESENTON_${name}`]

const APP_ID = "io.github.thmen89.chatppt"
// TODO(owner): Apple Developer Team ID, required for Mac App Store builds only.
const TEAM_ID = env("APPLE_TEAM_ID") || ""
const macTarget = env("MAC_TARGET")
const masDevProvisioningProfile = resolveProvisioningProfileForTarget({
  target: "mas-dev",
  label: "MAS development",
  candidates: [
    "build/AppleDevelopment.provisionprofile",
    "build/AppleDev.provisionprofile",
    "build/AppDev.provisionprofile",
  ],
})
const masProvisioningProfile = resolveProvisioningProfileForTarget({
  target: "mas",
  label: "Mac App Store distribution",
  candidates: ["build/MacAppStore.provisionprofile"],
})
const masDevIdentity =
  env("MAS_DEV_IDENTITY") || process.env.CSC_NAME || ""
const masDistributionIdentity =
  env("MAS_DISTRIBUTION_IDENTITY") ||
  env("MAS_IDENTITY") ||
  process.env.CSC_NAME ||
  ""
const appStoreBundleShortVersion =
  macTarget === "mas" ? getAppStoreBundleShortVersion() : undefined
const appStoreBundleVersion =
  macTarget === "mas"
    ? getAppStoreBundleVersion(appStoreBundleShortVersion)
    : undefined

function getAppStoreBundleShortVersion() {
  const configuredVersion = env("APP_STORE_VERSION")
  if (configuredVersion) {
    validateAppStoreVersion(configuredVersion, "CHATPPT_APP_STORE_VERSION")
    return configuredVersion
  }

  const match = /^(\d+)\.(\d+)\.(\d+)/.exec(packageMetadata.version)
  if (!match) {
    throw new Error(
      `Cannot derive an App Store version from package version "${packageMetadata.version}". Set CHATPPT_APP_STORE_VERSION to three period-separated integers, for example 1.0.0.`
    )
  }
  return `${match[1]}.${match[2]}.${match[3]}`
}

function getAppStoreBundleVersion(bundleShortVersion) {
  const configuredBuild = env("APP_STORE_BUILD")
  if (configuredBuild) {
    validateAppStoreBuild(configuredBuild, "CHATPPT_APP_STORE_BUILD")
    return configuredBuild
  }
  return bundleShortVersion
}

function validateAppStoreVersion(value, source) {
  if (!/^\d+\.\d+\.\d+$/.test(value)) {
    throw new Error(
      `${source} must be three period-separated integers, for example 1.0.0. Received: ${value}`
    )
  }
}

function validateAppStoreBuild(value, source) {
  if (!/^\d+(\.\d+){0,2}$/.test(value)) {
    throw new Error(
      `${source} must be one to three period-separated integers, for example 42 or 1.0.1. Received: ${value}`
    )
  }
}

function resolveProvisioningProfileForTarget({ target, label, candidates }) {
  try {
    return resolveProvisioningProfile({ target, label, candidates })
  } catch (error) {
    console.error(`\n${error.message}\n`)
    process.exit(1)
  }
}

function resolveProvisioningProfile({ target, label, candidates }) {
  if (macTarget !== target) {
    return undefined
  }

  if (process.platform !== "darwin") {
    throw new Error(
      `${label} builds must be run on macOS because Apple signing tools are required.`
    )
  }

  const undecodableProfiles = []

  for (const candidate of candidates) {
    const candidatePath = path.join(__dirname, candidate)
    if (!fs.existsSync(candidatePath)) {
      continue
    }

    try {
      execFileSync("security", ["cms", "-D", "-i", candidatePath], {
        stdio: "ignore",
      })
      return candidate
    } catch {
      undecodableProfiles.push(candidate)
    }
  }

  if (undecodableProfiles.length > 0) {
    throw new Error(
      `Found ${label} provisioning profile, but macOS could not decode it: ${undecodableProfiles.join(", ")}. Re-download the matching Apple provisioning profile and replace the local file.`
    )
  }

  throw new Error(
    `Missing ${label} provisioning profile. Expected: ${candidates.join(", ")}`
  )
}

// AfterPack hook: set executable permissions on macOS; no-op on Windows
const afterPack = async (context) => {
  if (context.electronPlatformName === "darwin") {
    const appPath = context.appOutDir
    const appBundleName = `${context.packager.appInfo.productFilename}.app`
    const resourcesRoot = path.join(
      appPath,
      appBundleName,
      "Contents",
      "Resources",
      "app",
      "resources"
    )
    const fastapiPath = path.join(resourcesRoot, "fastapi", "fastapi")
    const exportPyDir = path.join(resourcesRoot, "export", "py")
    const converterCandidates = [
      `convert-${process.platform}-${process.arch}`,
      `convert-${process.platform}`,
      "convert",
    ]

    console.log("Setting executable permissions for FastAPI binary...")
    console.log("FastAPI path:", fastapiPath)

    if (fs.existsSync(fastapiPath)) {
      fs.chmodSync(fastapiPath, 0o755)
      console.log("✓ Execute permissions set for FastAPI")
    } else {
      console.warn("⚠ FastAPI binary not found at:", fastapiPath)
    }

    console.log("Setting executable permissions for export converter binary...")
    let converterFound = false
    for (const candidate of converterCandidates) {
      const candidatePath = path.join(exportPyDir, candidate)
      if (fs.existsSync(candidatePath)) {
        fs.chmodSync(candidatePath, 0o755)
        console.log("✓ Execute permissions set for converter:", candidatePath)
        converterFound = true
      }
    }
    if (!converterFound) {
      console.warn("⚠ No converter binary found in:", exportPyDir)
    }

    const fastapiDir = path.join(resourcesRoot, "fastapi")
    if (fs.existsSync(fastapiDir)) {
      console.log("FastAPI directory contents:", fs.readdirSync(fastapiDir))
    }

    if (fs.existsSync(exportPyDir)) {
      console.log("Export py directory contents:", fs.readdirSync(exportPyDir))
    }
  }
}

const config = {
  appId: APP_ID,
  productName: "ChatPPT",
  asar: false,
  copyright: "Copyright © 2026 ChatPPT contributors. Derived from Presenton (Apache-2.0).",
  directories: {
    output: "dist",
    buildResources: "build",
  },
  files: [
    "resources",
    "app_dist",
    "node_modules",
    "NOTICE"
  ],
  afterPack,
  mac: {
    artifactName: "ChatPPT-${version}.${ext}",
    target: [macTarget || "dmg"],
    category: "public.app-category.productivity",
    hardenedRuntime: false,
    gatekeeperAssess: false,
    identity: macTarget === "mas-dev" ? null : undefined,
    icon: "resources/ui/assets/images/chatppt_mark.png",
    bundleShortVersion: appStoreBundleShortVersion,
    bundleVersion: appStoreBundleVersion,
    extendInfo: TEAM_ID ? { ElectronTeamID: TEAM_ID } : undefined,
  },
  masDev: {
    type: "development",
    identity: masDevIdentity || undefined,
    provisioningProfile: masDevProvisioningProfile,
    entitlements: "build/entitlements.mas.plist",
    entitlementsInherit: "build/entitlements.mas.inherit.plist",
    // osx-sign always adds --timestamp; this later flag keeps local MAS dev signing offline-tolerant.
    additionalArguments: ["--timestamp=none"],
  },
  mas: {
    type: "distribution",
    identity: masDistributionIdentity || undefined,
    provisioningProfile: masProvisioningProfile,
    entitlements: "build/entitlements.mas.plist",
    entitlementsInherit: "build/entitlements.mas.inherit.plist",
  },
  linux: {
    artifactName: "ChatPPT-${version}.${ext}",
    target: ["AppImage", "deb"],
    icon: "build/icons",
  },
  deb: {
    afterInstall: "build/after-install.tpl",
    recommends: ["libreoffice"],
  },
  win: {
    target: ["nsis", "appx"],
    icon: "build/icon.ico",
    artifactName: "ChatPPT-${version}.${ext}",
    executableName: "ChatPPT",
  },
  nsis: {
    oneClick: false,
    perMachine: false,
    allowToChangeInstallationDirectory: true,
    allowElevation: true,
    installerIcon: "build/icon.ico",
    uninstallerIcon: "build/icon.ico",
    installerHeaderIcon: "build/icon.ico",
    createDesktopShortcut: true,
    createStartMenuShortcut: true,
    shortcutName: "ChatPPT",
    uninstallDisplayName: "ChatPPT",
  },
  appx: {
    // TODO(owner): Microsoft Store identity (identityName, publisher CN, publisherDisplayName).
    identityName: "ChatPPT",
    publisher: "CN=TODO-OWNER",
    displayName: "ChatPPT",
    publisherDisplayName: "TODO-OWNER",
    applicationId: "ChatPPT",
  },
}

const targets = macTarget ? builder.Platform.MAC.createTarget([macTarget]) : undefined

builder.build({ targets, config })
