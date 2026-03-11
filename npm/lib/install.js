#!/usr/bin/env node

const { execSync, execFileSync } = require("child_process");
const { existsSync } = require("fs");

const PACKAGE = "openrag";
const VERSION = require("../package.json").version;
const SPEC = `${PACKAGE}==${VERSION}`;

function findPython() {
  for (const cmd of ["python3", "python"]) {
    try {
      const version = execFileSync(cmd, ["--version"], {
        encoding: "utf-8",
        stdio: ["pipe", "pipe", "pipe"],
      }).trim();

      const match = version.match(/Python (\d+)\.(\d+)/);
      if (match && (parseInt(match[1]) > 3 || (parseInt(match[1]) === 3 && parseInt(match[2]) >= 13))) {
        return cmd;
      }
    } catch {}
  }
  return null;
}

function findInstaller() {
  // Prefer uv, then pipx, then pip
  for (const cmd of ["uv", "pipx"]) {
    try {
      execFileSync(cmd, ["--version"], { stdio: "pipe" });
      return cmd;
    } catch {}
  }
  return "pip";
}

function install() {
  const python = findPython();
  if (!python) {
    console.error(
      `\x1b[31mError: Python >= 3.13 is required but was not found.\x1b[0m\n` +
        `Please install Python 3.13+ and try again.\n` +
        `  https://www.python.org/downloads/`
    );
    process.exit(1);
  }

  const installer = findInstaller();
  console.log(`Installing ${SPEC} using ${installer}...`);

  try {
    switch (installer) {
      case "uv":
        execSync(`uv tool install ${SPEC}`, { stdio: "inherit" });
        break;
      case "pipx":
        execSync(`pipx install ${SPEC}`, { stdio: "inherit" });
        break;
      default:
        execSync(`${python} -m pip install ${SPEC}`, { stdio: "inherit" });
        break;
    }
    console.log(`\x1b[32m${PACKAGE} installed successfully.\x1b[0m`);
  } catch (err) {
    console.error(`\x1b[31mFailed to install ${PACKAGE}.\x1b[0m`);
    console.error(
      `You can install it manually: pip install ${SPEC}`
    );
    process.exit(1);
  }
}

install();
