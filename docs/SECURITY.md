# Security model

This document describes how Tokser Backup Manager protects data and how to
deploy it safely. For reporting vulnerabilities see [../SECURITY.md](../SECURITY.md).

---

## Threat model

TBM assumes:

- The host is trusted; a root compromise is game over
- The network between the browser and the server may be untrusted → use HTTPS
- Backup sources may contain sensitive data and must not leak through logs, the
  API, or error messages
- Stored third-party credentials (bot tokens, storage passwords, database
  passwords) must survive a database leak without being usable

TBM does **not** attempt to protect against a malicious administrator — an
administrator can read any backup by design.

---

## Authentication

**Password storage.** Argon2id via `argon2-cffi` (3 iterations, 64 MiB, 2 lanes,
32-byte output). Legacy `$2*` bcrypt hashes are accepted and transparently
re-hashed at the next successful login. Minimum length is 10 characters with
both letters and digits, enforced server-side.

**Sessions.** A 256-bit random token is issued at login and stored in an
`HttpOnly`, `SameSite=Lax` cookie. Only the SHA-256 hash of the token is
persisted in `user_sessions`, so a database leak does not yield usable sessions.
Sessions expire after `TBM_SESSION_TTL` hours (default 12); expired rows are
deleted on access.

**Brute force.** Each failed attempt is recorded in `login_attempts`. After
`TBM_LOGIN_MAX_ATTEMPTS` (default 5) failures the account locks for
`TBM_LOGIN_LOCKOUT` minutes (default 15). Independently, a per-IP sliding window
limits overall request rate.

**Two-factor.** TOTP (RFC 6238, 30-second step, SHA-1, 6 digits, ±1 window) is
verified at login when `totp_enabled` is set. The shared secret is encrypted.
The enrollment UI is not yet built; see the roadmap.

---

## Authorization

Three roles with explicit permission lists:

| Role | Permissions |
|---|---|
| `admin` | `*` |
| `operator` | jobs read/write/run, backups read/write/restore/delete, sources, storage read, telegram, notifications, monitoring, logs, dashboard |
| `viewer` | read-only: jobs, backups, sources, storage, telegram, notifications, monitoring, logs, dashboard |

`require_permission(code)` is applied as a FastAPI dependency on every endpoint.
There is no endpoint that performs a privileged action without an explicit
dependency — verified by the RBAC tests.

Administrative invariants enforced in code:

- You cannot disable, demote or delete your own account
- The last active administrator cannot be deleted
- Deleting a user cascades to their sessions

---

## CSRF

`CSRFMiddleware` inspects every request. For `POST`/`PUT`/`PATCH`/`DELETE`
against `/api/` with a session cookie present, it resolves the session and
compares `X-CSRF-Token` against the stored token using a constant-time compare.
Mismatch → **403**. Login and setup are exempt because they establish the
session. Requests authenticated purely by `Authorization: Bearer` are exempt
because an attacker's page cannot set that header cross-origin.

The token is surfaced by `GET /auth/me` and by the login response; the frontend
stores it in memory and attaches it to every mutation.

---

## Secrets at rest

Everything sensitive is encrypted before it touches the database:

- Storage passwords and secret keys
- Telegram bot tokens
- Database passwords
- Per-job archive encryption passwords
- SMTP password
- TOTP shared secrets

Implementation: AES-256-GCM through `cryptography.fernet`-style key derivation —
the configured `TBM_ENCRYPTION_KEY` is hashed with SHA-256 to a 32-byte Fernet
key. A wrong key yields `InvalidToken`, which is caught and reported as an empty
value rather than crashing.

The API never returns decrypted secrets. Storage and Telegram responses expose
`has_secrets` and `bot_token_masked` only.

> Losing `TBM_ENCRYPTION_KEY` makes stored credentials unrecoverable. It does
> **not** affect the archives themselves — those use per-job passwords that only
> the operator knows.

---

## Archive encryption

Optional per job. AES-256-GCM, key derived from the password via PBKDF2-HMAC-
SHA256 with 390,000 iterations and a random 16-byte salt. The file begins with a
`TBME1` magic header, followed by the salt, an 8-byte nonce prefix, then a
sequence of `[length][ciphertext+tag]` chunks. Each 1 MiB chunk uses
`nonce_prefix || chunk_index` as its nonce, so nonces never repeat within a file.

Wrong passwords fail the GCM tag check and are reported as
"Wrong password or corrupted archive" — never silently producing garbage.

---

## Path safety

**Archive extraction.** Two independent guards:

1. `is_safe_archive_member` rejects absolute paths, drive letters, any `..`
   component and NUL bytes.
2. The target path is resolved and must be a descendant of the destination
   directory.

Symlink and hardlink members are only materialised when their target also
resolves inside the destination. Existing files are refused unless the caller
explicitly set `overwrite`. Tests cover `../../etc/passwd`, `/etc/passwd`,
`a/../../b` and `C:/Windows/system32`.

**Restore destinations.** Must be absolute; relative paths and traversal in
`selected_paths` are rejected at the schema layer with **422**.

**Backup sources.** Must be absolute. Symlinks are not followed unless the job
opts in.

**Static files.** Served by Starlette's `StaticFiles`, which normalises paths.

---

## Injection

**SQL.** Every query goes through SQLAlchemy's expression language or bound
parameters. There is no string-formatted SQL anywhere in the codebase.

**Command execution.** No `shell=True` and no `os.system`. Database dumps call
`subprocess.run([...])` with an argument list. MySQL credentials are written to
a temporary `0600` option file and deleted in a `finally` block, so they never
appear in `ps`. PostgreSQL uses `PGPASSWORD` in the child environment.

**XSS.** The frontend builds DOM through template strings but escapes every
dynamic value with `fmt.escape` before insertion. The Content-Security-Policy
restricts scripts to same-origin (`script-src 'self' 'unsafe-inline'` — inline
is required for the small bootstrap blocks in the login/setup pages, which
contain no interpolated user data).

---

## Transport and headers

Every response carries:

```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: geolocation=(), microphone=(), camera=()
Content-Security-Policy: default-src 'self'; img-src 'self' data:;
  style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline';
  connect-src 'self'; font-src 'self' data:; frame-ancestors 'none';
  base-uri 'self'; form-action 'self'
Strict-Transport-Security: max-age=31536000; includeSubDomains   (HTTPS only)
```

`HostValidationMiddleware` rejects unexpected `Host` headers when
`TBM_ALLOWED_HOSTS` is set, mitigating host-header injection behind a proxy.

---

## Least privilege

The systemd unit creates the service as the unprivileged `TBM` user with:

```
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=read-only
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
RestrictRealtime=true
LockPersonality=true
ReadWritePaths=<data> <logs> <backup dir>
```

**Never run the service as root.** A web vulnerability would then be a full
system compromise. Instead grant read + traverse access to one path at a time
with a POSIX ACL — the `tbm access` command wraps this:

```bash
sudo tbm access grant /root          # read-only; write is never granted
sudo tbm access grant /var/lib/mysql
sudo tbm access check  /root         # exit 0 when readable
sudo tbm access revoke /root
```

This does exactly:

```bash
sudo setfacl -R -m u:TBM:rX /root     # r = read files, X = traverse dirs
sudo tbm service restart              # pick up the new access
```

Prefer `tbm access` over `usermod -aG`: adding the account to a group such as
`docker` or `sudo` grants far more than read access to one directory.

Docker deployments drop all capabilities and set `no-new-privileges`.

---

## Audit trail

`activity_logs` records authentication successes and failures, job and backup
operations, restores, settings changes, user management, and storage/Telegram
changes — with user, IP, timestamp and severity. The panel exposes search and
level filters and allows downloading the raw application log.

Login failures are additionally stored in `login_attempts` for lockout
accounting.

---

## Hardening checklist

- [ ] `TBM_SECURE_COOKIE=true` and HTTPS terminated at Nginx
- [ ] `TBM_ALLOWED_HOSTS` set to the real hostname
- [ ] Application bound to `127.0.0.1`, reachable only through the proxy
- [ ] `.env` owned by `TBM:TBM`, mode `0600`
- [ ] `.env` backed up separately and securely
- [ ] Firewall permits only 80/443
- [ ] Panel not exposed publicly without a VPN or IP allowlist
- [ ] Two-factor enabled for administrators
- [ ] Log review scheduled
- [ ] Unattended upgrades enabled for the OS

---

## Known limitations

- No per-job source-level authorization: an operator who can edit a job can add
  any path the service user can read. Restrict the service user's group
  memberships to bound this.
- Rate limiting is in-process. Behind multiple workers each keeps its own
  counters; use the proxy's rate limiting for a global limit.
- The audit log is append-only in application logic but any administrator with
  database access can modify it.
