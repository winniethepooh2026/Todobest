# Noki production runbook

This runbook assumes a Linux host with DNS, TLS, PostgreSQL 18 and Redis 8
installed. The PostgreSQL role and database are provisioned explicitly by an
administrator; the application never receives database-creation privileges.
Celery does not officially support Windows; do not use a Windows workstation
as the production worker host.

PM2 supervises the four application processes (`noki-api`, `noki-worker`,
`noki-beat`, `noki-frontend`) via a single `ecosystem.config.cjs`. PostgreSQL,
Redis and the reverse proxy are infrastructure services and should not be
supervised by PM2.

## 1. Release and filesystem

Deploy a clean, reviewed Git commit. All Alembic revisions must be tracked by
Git and `git status --porcelain` must be empty.

Run the application and PM2 under one dedicated, unprivileged account that can
read the checkout. Set these two values to that real account before creating
runtime directories; the same account must run every non-`sudo` command later
in this runbook:

```bash
NOKI_SERVICE_USER=noki
NOKI_SERVICE_GROUP=noki
id "$NOKI_SERVICE_USER"

sudo install -d -o "$NOKI_SERVICE_USER" -g "$NOKI_SERVICE_GROUP" -m 0750 \
  /var/lib/noki/uploads \
  /var/lib/noki/celery
sudo install -d -m 0755 /var/log/noki
sudo install -d -o "$NOKI_SERVICE_USER" -g "$NOKI_SERVICE_GROUP" -m 0750 \
  /var/log/noki/backend \
  /var/log/noki/frontend
install -m 0600 .env.example .env
sudo chown "$NOKI_SERVICE_USER:$NOKI_SERVICE_GROUP" .env
```

Edit the single `.env`. `ecosystem.config.cjs` passes an explicit allowlist of
public/runtime keys to the frontend process and keeps backend secrets out.

Generate independent values:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"  # PostgreSQL
python3 -c "import secrets; print(secrets.token_urlsafe(32))"  # Redis
python3 -c "import secrets; print(secrets.token_urlsafe(64))"  # JWT
python3 -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

Set the PostgreSQL password once in `POSTGRES_PASSWORD`; Noki builds the
SQLAlchemy URL from `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`,
`POSTGRES_USER` and `POSTGRES_PASSWORD` with correct URL escaping. Do not edit
`backend/app/core/config.py`, and do not add `DATABASE_URL` to a new env file.
`DATABASE_URL` remains only as a backwards-compatible advanced override for
existing deployments. If an old env file contains both representations, remove
`DATABASE_URL` after copying its real values into `POSTGRES_*`; production
validation refuses partial or duplicate definitions.

The Redis password is still copied into its matching Redis connection URL. Set
the real HTTPS domain in `BACKEND_URL`, `FRONTEND_URL`, `CORS_ORIGINS` and
`GOOGLE_REDIRECT_URI`. Set `TRUSTED_HOSTS` to the public hostname plus
`127.0.0.1`, without schemes, ports or wildcards. Keep
`NEXT_PUBLIC_API_URL=/api/v1` so browser requests remain same-origin, and keep
`EXPECTED_DB_REVISION=0026_totp`.

`ENABLE_HSTS=true` is required by the validator in both env files. Browsers
ignore the `Strict-Transport-Security` header on plain HTTP responses, so this
is harmless while nginx only listens on `:80` — just don't expose a broken or
self-signed `:443` in the meantime, or any browser that accepts it once will
pin HSTS and lock itself out of the site until the real certificate is live.

The validator also reserves PostgreSQL connection headroom:
`UVICORN_WORKERS * (DB_POOL_SIZE + DB_MAX_OVERFLOW)` must be at most 80. The
template's `1 * (10 + 20) = 30` is safe for a conventional 100-connection
PostgreSQL instance; change it only after accounting for migrations, workers,
administration and monitoring connections.

`UVICORN_LIMIT_CONCURRENCY=200` bounds in-flight connections per Uvicorn worker
so a burst cannot consume file descriptors and memory without limit. Tune it
only after observing latency, worker count and host capacity.

The API Redis pool is bounded by `REDIS_MAX_CONNECTIONS=50`; preflight also
requires `UVICORN_WORKERS * REDIS_MAX_CONNECTIONS <= 1000`.

The documented topology uses loopback PostgreSQL and Redis. If PM2 connects to
a remote PostgreSQL host, set `DATABASE_SSL_CA_FILE` to an absolute readable CA
bundle path. API, migrations and cleanup worker then use the same
`CERT_REQUIRED` TLS context with hostname verification. URL query TLS modes
such as `ssl=require` are rejected because they do not prove server identity.
Remote Redis must use `rediss://`; TLS-override query parameters are rejected.

PM2 trusts forwarded headers only from `127.0.0.1` (`FORWARDED_ALLOW_IPS`).

### Private S3 avatar storage

Google avatars are optional for authentication but, when enabled, all four
storage values must be configured together:

```dotenv
AWS_ACCESS_KEY_ID=REPLACE_WITH_DEDICATED_KEY
AWS_SECRET_ACCESS_KEY=REPLACE_WITH_DEDICATED_SECRET
AWS_STORAGE_BUCKET_NAME=noki-private-avatars
AWS_S3_ENDPOINT_URL=https://s3.example-provider.com
AWS_S3_REGION_NAME=us-east-1
CLAMAV_UNIX_SOCKET=/run/clamav/clamd.ctl
```

The endpoint is configuration, never request input. Production validation
requires an HTTPS origin without credentials, path, query or fragment. The
credentials, bucket and endpoint are passed only to the API and Celery worker;
never expose them through `NEXT_PUBLIC_*`, browser bundles or logs. This release's
four-variable storage contract requires explicit static credentials and does
not support ambient AWS workload-role credentials. Use a dedicated application
principal, rotate its key on a documented schedule, and never reuse a personal
or administrator key.

Use a dedicated private bucket or prefix with:

- all four S3 Block Public Access controls enabled;
- Object Ownership set to `Bucket owner enforced` and ACLs disabled;
- default server-side encryption enabled (SSE-S3 is sufficient unless a
  separate compliance policy requires KMS);
- a bucket policy denying requests when `aws:SecureTransport` is false;
- no website hosting, public-read ACLs or anonymous bucket policy;
- versioning disabled for this immutable-key workload, or an explicit rule
  that quickly expires non-current versions and delete markers.

The application never needs bucket-policy or ACL administration. A minimal
AWS IAM policy is scoped to the application prefix; replace the placeholders
and adapt the syntax for a non-AWS provider:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::BUCKET_NAME/avatars/*"
    },
    {
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::BUCKET_NAME",
      "Condition": {"StringLike": {"s3:prefix": ["avatars/*"]}}
    }
  ]
}
```

`ListBucket` exists only for the daily orphan reconciler. It follows every S3
continuation token rather than silently stopping at the first 10,000 objects.
As a memory/request safety guard it fails the task loudly after 100 pages
(at most 100,000 provider records per run); alert on the Celery task failure
and review inventory, request cost and capacity before raising that guard.
Remove `ListBucket` if reconciliation is replaced by a durable outbox. Do not
grant `s3:*`, `s3:PutObjectAcl`, bucket deletion or bucket configuration
actions.

With the required four environment variables, PM2 necessarily gives the API
and worker the same dedicated key. Consequently that principal combines the
API's `GetObject` need with the worker's `PutObject`, `DeleteObject` and
`ListBucket` needs. This is a known least-privilege boundary, not process-level
credential separation. Supporting distinct read/write principals requires a
separate configuration contract and deployment change; do not improvise extra
unvalidated variables in production.

Avatar objects use immutable content-hash keys and one small `PutObject`; the
browser receives only the authenticated same-origin `/media/avatars/...`
route. Keep `Cache-Control: private, max-age=31536000, immutable` so repeated
board renders do not create repeated S3 GET charges. `private` prevents shared
proxy/CDN caches from storing an authenticated response; do not replace it
with `public` or `s-maxage`. The response intentionally has no `Vary: Cookie`,
because the immutable user/content-hash URL already identifies the bytes and
cookie rotation would fragment the browser cache. Authentication, current DB
state and shared-space authorization are still checked on every request,
including conditional and in-process-cache hits.

Each API process also keeps a thread-safe, content-hash-keyed LRU of verified
avatar bytes, bounded to 32 MiB. On an S3 miss it reads no more than the
configured normalized-avatar cap and verifies the exact body length and
SHA-256 before caching; metadata alone is not trusted. This cache contains no
RBAC decisions and is neither shared across Uvicorn workers nor a substitute
for the private HTTP cache directive. Account for up to 32 MiB per API worker
when setting memory limits. Do not add presigned browser PUTs: they would
bypass the mandatory validation and malware gate.

Configure a lifecycle rule to abort incomplete multipart uploads after one
day even though the current avatar path uses single-part PUTs. If versioning
is enabled, also expire non-current avatar versions and delete markers
promptly. Use the hot/default storage class for these tiny frequently read
objects; archival classes and per-object monitoring usually cost more than
they save here.

### ClamAV fail-closed gate

Install `clamav-daemon` and `clamav-freshclam` as host services. Keep `clamd`
on a local Unix socket; its TCP protocol is neither authenticated nor
encrypted and must not be exposed to the network. Grant the Noki worker only
the group permission required to connect to the socket. Configure
`StreamMaxLength` and the clamd scan/file/time limits slightly above the avatar
source limit, while keeping archive recursion and total scanned bytes bounded.
Enable and monitor automatic signature updates.

Before each S3 PUT the worker scans the bounded original bytes, decodes and
normalizes only static JPEG/PNG/WebP, strips metadata, enforces an encoded size
cap, and scans the exact normalized WebP again. `FOUND`, timeout, malformed
reply, stream-limit error or an unavailable scanner all stop the pipeline;
authentication still succeeds with the initials fallback, but no object is
sent to S3.

`AVATAR_MALWARE_SCAN_MODE` defaults to `required`. A closed test deployment
that accepts only trusted test accounts may temporarily set it to
`disabled-for-testing`. This bypass is deliberately explicit, is routed only
to the worker process, and emits a security warning for every skipped scan.
The URL, media type, byte, pixel and dimension limits, static-image decoding,
normalization, metadata stripping, output cap and private S3 contract remain
enforced. Restore `required` and restart the worker before admitting external
accounts; never use the bypass as an availability fallback in production.

Before opening traffic, verify without printing credentials:

```bash
systemctl is-active clamav-daemon clamav-freshclam
clamdscan --version
make pm2-check
```

Run one provider-specific smoke test using the application principal: put a
small disposable object under `avatars/smoke/`, read it, delete it, and confirm
that public/anonymous reads fail. Do this at deployment time, not from the
five-second `/health` endpoint; continuous PUT/GET probes are billable.

Validate the root backend `.env` and Alembic topology without connecting to or
changing the database:

```bash
make pm2-check
```

This check rejects development/template values, incomplete or conflicting
PostgreSQL variables, a malformed encryption key, insecure cookies/CORS,
wildcard or untrusted hosts, case-variant/duplicate env declarations, unsafe
capacity combinations, an unexpected database revision and relative backend
runtime paths. It never creates the database or tables.

## 2. Backup and migration gate

Before every schema migration:

1. enable a maintenance window or otherwise stop writes;
2. create a PostgreSQL custom-format dump;
3. snapshot the local Page upload directory;
4. record the private avatar bucket version/inventory state and verify that
   its retention/lifecycle policy matches the database backup timestamp;
5. verify that the dump can be read and that the encryption key and S3
   credentials are backed up separately from the database;
6. record the current application commit and `alembic current`.

The release has exactly one expected Alembic head:
`0026_totp`. The migration launcher verifies that topology before
upgrading and refuses to report success unless the database reaches that
revision.

```bash
pg_dump \
  --host=POSTGRES_HOST_VALUE \
  --port=POSTGRES_PORT_VALUE \
  --username=POSTGRES_USER_VALUE \
  --dbname=POSTGRES_DB_VALUE \
  --format=custom \
  --file=/secure-backups/noki-before-deploy.dump
pg_restore --list /secure-backups/noki-before-deploy.dump >/dev/null
```

Replace every `*_VALUE` placeholder with the exact non-secret connection value
from `.env`; `pg_dump` prompts for the password. For a remote database, also set
`PGSSLMODE=verify-full` and `PGSSLROOTCERT` to the same CA bundle represented by
`DATABASE_SSL_CA_FILE`. Verify the dump came from the intended host, port and
database before confirming the migration gate.

Migration `0002_secure_content` encrypts existing content and drops the old
plaintext columns. An application-only rollback is therefore not safe. The
rollback unit is the old release plus the matching PostgreSQL, local upload
and private avatar-bucket snapshots/inventory state.

Migration `0004_system_statuses` may stop if adding missing system columns would
take a board above ten columns. Review boards with more than seven columns
before the maintenance window.

## 2. TLS certificate

Before enabling HTTPS, obtain a Let's Encrypt certificate. The repository
includes two nginx configurations:

- [`nginx.initial.conf`](nginx.initial.conf) — port 80 only, no SSL. Use this
  for the initial certbot run and for any subsequent renewals; the
  `/.well-known/acme-challenge/` location must remain reachable over plain HTTP
  even after HTTPS is enabled.
- [`nginx.conf`](nginx.conf) — full HTTPS configuration. Apply this **only
  after** certbot has successfully issued the certificate.

Workflow:

```bash
# 1. Remove any existing nginx config for this domain to avoid conflicts.
sudo rm -f /etc/nginx/sites-enabled/noki
sudo rm -f /etc/nginx/sites-available/noki
sudo rm -f /etc/nginx/sites-enabled/noki.click
sudo rm -f /etc/nginx/sites-available/noki.click

# 2. Create the ACME challenge directory and set permissions.
sudo mkdir -p /var/www/html/.well-known/acme-challenge
sudo chown -R www-data:www-data /var/www/html/.well-known

# 3. Write the initial config directly (do NOT use cp, it may append to existing file).
sudo tee /etc/nginx/sites-available/noki > /dev/null << 'EOF'
server {
    listen 80;
    listen [::]:80;
    server_name noki.click;
    server_tokens off;
    location /.well-known/acme-challenge/ {
        root /var/www/html;
        autoindex off;
    }
    location / {
        proxy_pass http://127.0.0.1:8010;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 10s;
        proxy_read_timeout 120s;
        proxy_send_timeout 120s;
    }
}
EOF

# 4. Activate the config.
sudo ln -sf /etc/nginx/sites-available/noki /etc/nginx/sites-enabled/

# 5. Verify the config is valid.
sudo nginx -t

# 6. Verify there is exactly ONE server block for this domain.
sudo nginx -T 2>/dev/null | grep -c "server_name noki.click"
# Should output: 1

# 7. Reload nginx.
sudo systemctl reload nginx

# 8. Verify the ACME challenge is reachable (should return 200, not 403).
curl -I http://noki.click/.well-known/acme-challenge/

# 9. Obtain the certificate (webroot method, does not stop the site).
sudo certbot certonly --webroot -w /var/www/html -d noki.click

# 10. Switch to the full HTTPS config.
sudo cp nginx.conf /etc/nginx/sites-available/noki
sudo nginx -t && sudo systemctl reload nginx

# 11. Test automatic renewal.
sudo certbot renew --dry-run
```

If you later move the ACME challenge to a dedicated port or a different path,
update both nginx configs and the certbot command accordingly.

## 3. PM2 deployment

PM2 deployment requires a host virtualenv and a completed Next production
build. PM2 cluster mode does not load-balance Python, so the PM2 daemon starts
one Uvicorn master and Uvicorn owns its configured worker count.

Install dependencies and build the frontend. The same-origin `/api/v1`
browser URL is the default, so the build does not require an env file:

```bash
python3.13 -m venv backend/.venv
backend/.venv/bin/python -m pip install --disable-pip-version-check ./backend

npm --prefix frontend ci
npm --prefix frontend run verify
npm --prefix frontend run audit:production
npm --prefix frontend prune --omit=dev
```

`NEXT_PUBLIC_API_URL` and the security-header configuration are frozen during
`next build`; changing them requires a rebuild. Pruning after
the checks keeps ESLint, TypeScript and other build-only packages off the
runtime host.

Before the first deployment, create a restricted login role and the database
manually through the local PostgreSQL administrator. Use the names from
`POSTGRES_USER` and `POSTGRES_DB`; set the prompted password to the exact
`POSTGRES_PASSWORD` value from `.env` without placing it in shell history:

```bash
sudo systemctl enable --now postgresql

# Copy these three non-secret values from .env. Do not source the whole file.
DB_PORT=5432
DB_ROLE=noki
DB_NAME=noki

sudo -u postgres pg_isready --port="$DB_PORT"
sudo -u postgres createuser --login --no-superuser --no-createdb --no-createrole \
  --no-replication --no-bypassrls --port="$DB_PORT" "$DB_ROLE"
sudo -u postgres psql --port="$DB_PORT" --command="\password $DB_ROLE"
sudo -u postgres createdb --port="$DB_PORT" --owner="$DB_ROLE" \
  --encoding=UTF8 --template=template0 "$DB_NAME"
```

For a remote or managed PostgreSQL service, perform the equivalent provisioning
through the provider. Confirm that the role has no `SUPERUSER`, `CREATEDB`,
`CREATEROLE`, `REPLICATION` or `BYPASSRLS` privileges.

After the database exists, validate the ecosystem and apply the explicit
one-shot Alembic migration. On the first empty database the backup confirmation
records that you verified the target is empty; on every later release create
and verify the backup described above first:

```bash
make pm2-check
make BACKUP_CONFIRMED=YES pm2-migrate
```

For a remote database, also configure `DATABASE_SSL_CA_FILE`. Neither `git
pull`, `pm2 start` nor API startup creates or migrates a database. Alembic,
rather than `Base.metadata.create_all`, is the only table-creation path.

Install and record the reviewed PM2 release, then start or update the complete
ecosystem. `startOrRestart` also handles the first start, and `--update-env`
prevents PM2 from retaining values from an older release:

```bash
sudo npm install --global pm2@7.0.3
test "$(pm2 --version)" = "7.0.3"

pm2 startOrRestart ecosystem.config.cjs --env production --update-env
make pm2-backfill
pm2 status
pm2 save
pm2 startup systemd
```

Follow the printed `pm2 startup` command to enable the generated systemd unit,
then run `pm2 save` once more. PM2 file logs must have bounded rotation before
opening traffic. One supported option is native logrotate:

```text
# /etc/logrotate.d/noki
/var/log/noki/backend/*.log /var/log/noki/frontend/*.log {
    daily
    maxsize 50M
    rotate 14
    missingok
    notifempty
    compress
    delaycompress
    copytruncate
}
```

Validate with `logrotate --debug`. A reviewed `pm2-logrotate` configuration is
also acceptable only if `max_size`, `retain` and compression are set
explicitly.

The PM2 dump contains injected secrets. Keep the PM2 home private:

```bash
sudo chmod 0700 "$HOME/.pm2"
sudo chmod 0600 "$HOME/.pm2/dump.pm2"
```

The ecosystem defines:

- one production Next.js process;
- one PM2 fork running Uvicorn with `UVICORN_WORKERS`;
- one Celery worker with bounded concurrency and child recycling;
- exactly one Celery Beat using persistent schedule state;
- absolute working directories/interpreters;
- no file watching;
- bounded restart loops, memory restart thresholds, timestamped logs and
  30–60 second graceful shutdown windows.

The backend processes receive the root `.env`; the frontend receives only an
explicit allowlist of public/runtime values. Treat this as the actual boundary rather than an OS user
separation; if you later split `noki`/`noki-web` accounts for defense in depth,
start each PM2 daemon with `--only noki-frontend` /
`--only noki-api,noki-worker,noki-beat` under its own user, pointing each at
its own env file.

Uvicorn's standard access log is disabled because an OAuth callback query
string can contain short-lived `code` and `state` values. The application
emits its own request log using only the sanitized path; keep that behavior
when changing the process command. Uvicorn's `Server` fingerprint header is
disabled as well.

`pm2 reload` is not zero-downtime for Python fork processes. Treat API restart
as a controlled restart unless a load-balanced multi-host topology has been
tested.

### Updating an existing release

Never deploy with only `git pull` followed by individual `pm2 restart`
commands. That leaves old Python dependencies, a stale Next build or stale PM2
environment values in memory. During a maintenance window, as the same
unprivileged PM2 account, use this order after reviewing the target commit and
creating the backups described above:

```bash
git pull --ff-only
backend/.venv/bin/python -m pip install --disable-pip-version-check --upgrade ./backend

npm --prefix frontend ci
npm --prefix frontend run verify
npm --prefix frontend run audit:production
npm --prefix frontend prune --omit=dev

make pm2-check
make BACKUP_CONFIRMED=YES pm2-migrate
pm2 startOrRestart ecosystem.config.cjs --env production --update-env
make pm2-backfill
pm2 status
pm2 save
```

The migration launcher builds indexes on existing tables with PostgreSQL
`CREATE INDEX CONCURRENTLY` and then backfills legacy account verification,
Space ownership, encrypted title indexes, and upload Space ids in
resumable 250-row transactions. Run
`make pm2-backfill` once more after PM2 reload so rows written by the old
application during migration are also covered.

If any command fails, do not restart the old healthy processes. Investigate
the failed preflight/build/migration first. `pm2-check` executes the ecosystem
configuration, verifies runtime directory access, imports the API and worker
modules (including optional provider SDKs such as `boto3`), checks installed
Python dependency consistency and validates Alembic topology before a process
is touched.

## 4. Reverse proxy and TLS

Expose only TCP 443 (and TCP 80 for the HTTPS redirect and ACME challenges).
Route:

- `/api/v1/` to `http://127.0.0.1:8010`;
- everything else, including `/media/`, to `http://127.0.0.1:3010`.

The Next rewrites proxy authenticated `/media/images/...` and
`/media/avatars/...` requests to the internal backend. Avatar objects remain
private in S3; do not expose the provider endpoint directly. Do not publish
backend `/docs`, `/openapi.json` or `/health`; monitor health over loopback.

At the proxy, preserve `Host`, set trusted `X-Forwarded-*` headers, impose a
request body limit slightly above 26 MiB, add login/register rate limits and set
TLS/HSTS headers on API responses as well as frontend responses. Reject unknown
Host values. The Next server adds CSP, frame, MIME-sniffing, referrer, opener,
resource and permissions headers to frontend responses.

The current CSP retains `script-src 'unsafe-inline'` because the verified
Next.js 16 static output contains inline React Flight bootstrap scripts without
nonces. Removing it breaks hydration. Treat this as a known residual risk:
moving to a nonce-based, fully dynamic render path (or a reviewed stable SRI
setup) requires a separate change and browser regression test.

If the proxy is not on loopback, update Uvicorn's trusted forwarded IPs; never
trust arbitrary public proxy headers.

## 5. Acceptance checks

Do not open the service to the team until all checks pass:

```bash
curl --fail --silent http://127.0.0.1:8010/live
curl --fail --silent http://127.0.0.1:8010/health
curl --fail --silent --head http://127.0.0.1:3010/
curl --fail --silent --head https://YOUR_DOMAIN/
```

Also verify:

- `/live` is process liveness, while the five-second cached `/health` readiness
  payload reports migrations, encryption, PostgreSQL, Redis and storage as
  healthy;
- PM2 processes have stable uptime and zero restart loops;
- the Celery worker answers `inspect ping` and only one Beat exists;
- HTTPS cookies contain `Secure`, auth cookies contain `HttpOnly`, and
  `SameSite=Lax` is present;
- a hostile Origin is rejected and PostgreSQL/Redis/3000/8000 are not publicly
  reachable;
- register/login/refresh/logout work through the public URL;
- Space, Team, Issue and Page operations work;
- an image remains available after application restart;
- a Google account with a valid profile photo eventually shows its avatar on
  board cards and in the assignee picker, while a missing/invalid photo safely
  falls back to initials;
- anonymous and unrelated-account avatar reads return 401/404, a shared-space
  member can read the avatar, and matching strong, weak, list or wildcard
  `If-None-Match` values return 304 without an S3 object read;
- an EICAR scanner smoke test is rejected before S3 and a clamd outage leaves
  authentication working but creates no avatar object;
- logs contain no secrets, authorization headers, page/issue plaintext or
  unexpected tracebacks;
- reboot restores the intended process set;
- a restore drill has been completed.

## 6. Monitoring and rollback

Monitor at minimum:

- HTTPS availability and backend `/health`;
- PM2 restart counts;
- PostgreSQL connections/storage/backup age;
- Redis memory, persistence and rejected connections;
- upload filesystem free space;
- S3 request/error/storage growth, private-access controls, orphan-cleanup
  failures (especially the explicit pagination safety limit) and lifecycle-rule
  effectiveness;
- clamd health, scan errors and `freshclam` signature age;
- Celery queue depth and Beat/worker heartbeat;
- application error rate and log disk usage.

On failed migration or encrypted-data errors, stop all application processes.
Do not rotate `DATA_ENCRYPTION_KEY` and do not repeatedly restart against an
unknown schema. Restore the matching database/local-upload/private-avatar
snapshots, deploy the recorded previous commit, verify health privately, and
only then reopen traffic. Do not delete the private bucket during rollback;
first disable writes and retain its namespace so stale URLs cannot be captured
by another account or provider tenant.
