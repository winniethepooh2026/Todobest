"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const DATABASE_ENV_KEYS = new Set([
  "POSTGRES_HOST",
  "POSTGRES_PORT",
  "POSTGRES_DB",
  "POSTGRES_USER",
  "POSTGRES_PASSWORD",
  "DATABASE_URL",
  "DATABASE_SSL_CA_FILE",
]);
const root = path.resolve(__dirname, "..");
const backend = path.join(root, "backend");
const defaultPython = path.join(
  backend,
  ".venv",
  process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
);
const python = process.env.NOKI_PYTHON || defaultPython;
const validateOnly = process.argv.includes("--validate-only");

if (
  !validateOnly &&
  process.env.NOKI_BACKUP_CONFIRMED !== "YES" &&
  !process.argv.includes("--backup-confirmed")
) {
  throw new Error(
    "Refusing to migrate without NOKI_BACKUP_CONFIRMED=YES. " +
      "Create and verify the PostgreSQL backup and preserve DATA_ENCRYPTION_KEY first.",
  );
}
if (!fs.existsSync(python)) {
  throw new Error(`Production Python executable does not exist: ${python}`);
}

const envFile = path.join(root, ".env");
if (!fs.existsSync(envFile)) {
  throw new Error(`Production .env does not exist: ${envFile}`);
}
const envSource = fs.readFileSync(envFile, "utf8");
const seenKeys = new Map();
for (const [index, line] of envSource.split(/\r?\n/u).entries()) {
  const match = line.match(/^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=/u);
  if (!match) continue;
  const normalized = match[1].toUpperCase();
  if (seenKeys.has(normalized)) {
    throw new Error(
      `.env contains duplicate key ${match[1]} on lines ${seenKeys.get(normalized)} and ${index + 1}`,
    );
  }
  seenKeys.set(normalized, index + 1);
}
const values = {};
for (const line of envSource.split(/\r?\n/u)) {
  const match = line.match(/^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$/u);
  if (!match) continue;
  let value = match[2];
  if (
    value.length >= 2 &&
    ((value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'")))
  ) {
    value = value.slice(1, -1);
  }
  values[match[1]] = value;
}
for (const key of Object.keys(values)) {
  const normalized = key.toUpperCase();
  if (DATABASE_ENV_KEYS.has(normalized) && key !== normalized) {
    throw new Error(`Use the canonical uppercase database variable ${normalized}, not ${key}`);
  }
}

if (values.ENVIRONMENT?.trim() !== "production") {
  throw new Error("ENVIRONMENT must be production");
}
const expectedDbRevision = values.EXPECTED_DB_REVISION?.trim() || "";
if (!/^[0-9][0-9A-Za-z_]{0,127}$/u.test(expectedDbRevision)) {
  throw new Error("EXPECTED_DB_REVISION is missing or invalid");
}

const childEnv = {
  ...Object.fromEntries(
    ["PATH", "HOME", "LANG", "LC_ALL", "TZ", "SYSTEMROOT", "WINDIR"]
      .filter((key) => process.env[key] !== undefined)
      .map((key) => [key, process.env[key]]),
  ),
  ...values,
  PYTHONDONTWRITEBYTECODE: "1",
  PYTHONUNBUFFERED: "1",
};

function runAlembic(...args) {
  const result = spawnSync(python, ["-m", "alembic", ...args], {
    cwd: backend,
    env: childEnv,
    stdio: "inherit",
    windowsHide: true,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
}

function runBackendModule(...args) {
  const result = spawnSync(python, ["-m", ...args], {
    cwd: backend,
    env: childEnv,
    stdio: "inherit",
    windowsHide: true,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
}

function captureAlembic(...args) {
  const result = spawnSync(python, ["-m", "alembic", ...args], {
    cwd: backend,
    env: childEnv,
    encoding: "utf8",
    windowsHide: true,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    if (result.stdout) process.stdout.write(result.stdout);
    if (result.stderr) process.stderr.write(result.stderr);
    process.exit(result.status ?? 1);
  }
  if (result.stderr) process.stderr.write(result.stderr);
  return result.stdout.trim();
}

function revisionIds(output) {
  return output
    .split(/\r?\n/u)
    .map((line) => line.trim())
    .map((line) => line.match(/^([0-9][0-9A-Za-z_]*)(?:\s|$)/u)?.[1])
    .filter(Boolean);
}

const settingsCheck = spawnSync(
  python,
  [
    "-c",
    [
      "from app.core.config import settings",
      "assert settings.environment == 'production'",
      "import app.main",
      "import app.worker.tasks",
      "print('Backend runtime imports are valid.')",
    ].join("\n"),
  ],
  {
    cwd: backend,
    env: childEnv,
    stdio: "inherit",
    windowsHide: true,
  },
);
if (settingsCheck.error) throw settingsCheck.error;
if (settingsCheck.status !== 0) process.exit(settingsCheck.status ?? 1);

const dependencyCheck = spawnSync(python, ["-m", "pip", "check"], {
  cwd: backend,
  env: childEnv,
  stdio: "inherit",
  windowsHide: true,
});
if (dependencyCheck.error) throw dependencyCheck.error;
if (dependencyCheck.status !== 0) process.exit(dependencyCheck.status ?? 1);

process.stdout.write("Verifying Alembic topology...\n");
const heads = captureAlembic("heads");
process.stdout.write(`${heads}\n`);
const headIds = revisionIds(heads);
if (headIds.length !== 1 || headIds[0] !== expectedDbRevision) {
  throw new Error(
    `Expected the single Alembic head ${expectedDbRevision}; migration refused.`,
  );
}

if (validateOnly) {
  process.stdout.write("Production .env and Alembic topology are valid.\n");
} else {
  process.stdout.write("Current database revision before migration:\n");
  const currentBefore = captureAlembic("current");
  process.stdout.write(`${currentBefore || "(unversioned database)"}\n`);
  process.stdout.write("Applying one-shot production migration...\n");
  runAlembic("upgrade", "head");
  process.stdout.write("Backfilling existing rows in resumable batches...\n");
  runBackendModule("app.cli", "backfill-production-data", "--batch-size", "250");
  process.stdout.write("Current database revision after migration:\n");
  const currentAfter = captureAlembic("current");
  process.stdout.write(`${currentAfter}\n`);
  const currentIds = revisionIds(currentAfter);
  if (currentIds.length !== 1 || currentIds[0] !== expectedDbRevision) {
    throw new Error(
      `Database did not reach expected revision ${expectedDbRevision}; keep traffic closed.`,
    );
  }
}
