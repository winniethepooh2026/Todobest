"use strict";

const path = require("node:path");
const fs = require("node:fs");

const root = __dirname;
const backendDir = path.join(root, "backend");
const frontendDir = path.join(root, "frontend");

// One optional .env file is enough. Variables supplied by the shell/PM2 win.
const envFile = path.join(root, ".env");
if (fs.existsSync(envFile)) {
  for (const line of fs.readFileSync(envFile, "utf8").split(/\r?\n/u)) {
    const match = line.match(/^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$/u);
    if (!match || process.env[match[1]] !== undefined) continue;
    let value = match[2];
    if (
      value.length >= 2 &&
      ((value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'")))
    ) {
      value = value.slice(1, -1);
    }
    process.env[match[1]] = value;
  }
}

const env = process.env;
const python = env.NOKI_PYTHON || path.join(
  backendDir,
  ".venv",
  process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
);
const nextCli = path.join(frontendDir, "node_modules", "next", "dist", "bin", "next");
const backendPort = env.BACKEND_PORT || "8010";
const frontendPort = env.FRONTEND_PORT || env.PORT || "3015";
const mailQueue = env.MAIL_QUEUE || "mail_queue";

const sharedEnv = {
  ...env,
  ENVIRONMENT: env.ENVIRONMENT || "production",
  PYTHONDONTWRITEBYTECODE: "1",
  PYTHONUNBUFFERED: "1",
};
const frontendEnv = {
  PATH: env.PATH,
  HOME: env.HOME,
  LANG: env.LANG,
  TZ: env.TZ,
  NODE_ENV: "production",
  NEXT_TELEMETRY_DISABLED: "1",
  NEXT_PUBLIC_API_URL: env.NEXT_PUBLIC_API_URL || "/api/v1",
  NEXT_PUBLIC_SITE_URL: env.NEXT_PUBLIC_SITE_URL || env.FRONTEND_URL || "https://noki.click",
  NEXT_PUBLIC_YANDEX_METRIKA_ID: env.NEXT_PUBLIC_YANDEX_METRIKA_ID || "",
  BACKEND_INTERNAL_URL: env.BACKEND_INTERNAL_URL || `http://127.0.0.1:${backendPort}`,
  ENABLE_HSTS: env.ENABLE_HSTS || "false",
  PORT: frontendPort,
};

function defaults(name, memory, processEnv = sharedEnv) {
  return {
    name,
    namespace: "noki",
    instances: 1,
    exec_mode: "fork",
    autorestart: true,
    watch: false,
    restart_delay: 2000,
    kill_timeout: 30000,
    max_memory_restart: memory,
    merge_logs: true,
    time: true,
    env: processEnv,
  };
}

module.exports = {
  apps: [
    {
      ...defaults("noki-api", "768M"),
      cwd: backendDir,
      script: python,
      interpreter: "none",
      args: [
        "-m", "uvicorn", "app.main:app",
        "--host", env.BACKEND_HOST || "127.0.0.1",
        "--port", backendPort,
        "--workers", env.UVICORN_WORKERS || "1",
        "--proxy-headers",
        "--forwarded-allow-ips", env.FORWARDED_ALLOW_IPS || "127.0.0.1",
      ],
    },
    {
      ...defaults("noki-worker", "512M"),
      cwd: backendDir,
      script: python,
      interpreter: "none",
      kill_timeout: 60000,
      args: [
        "-m", "celery", "-A", "app.worker.celery_app:celery_app", "worker",
        "--loglevel=INFO",
        `--concurrency=${env.CELERY_WORKER_CONCURRENCY || "1"}`,
        "--queues=celery",
        "--hostname=noki-worker@%h",
      ],
    },
    {
      ...defaults("noki-mail-worker", "256M"),
      cwd: backendDir,
      script: python,
      interpreter: "none",
      kill_timeout: 60000,
      args: [
        "-m", "celery", "-A", "app.worker.celery_app:celery_app", "worker",
        "--loglevel=INFO",
        `--concurrency=${env.CELERY_MAIL_WORKER_CONCURRENCY || "2"}`,
        `--queues=${mailQueue}`,
        "--hostname=noki-mail-worker@%h",
      ],
    },
    {
      ...defaults("noki-beat", "256M"),
      cwd: backendDir,
      script: python,
      interpreter: "none",
      args: [
        "-m", "celery", "-A", "app.worker.celery_app:celery_app", "beat",
        "--loglevel=INFO",
        `--schedule=${env.CELERY_BEAT_SCHEDULE || path.join(backendDir, "celerybeat-schedule")}`,
      ],
    },
    {
      ...defaults("noki-frontend", "768M", frontendEnv),
      cwd: frontendDir,
      script: nextCli,
      interpreter: process.execPath,
      args: ["start", "--hostname", "127.0.0.1", "--port", frontendPort],
    },
  ],
};
