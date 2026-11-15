# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 1.0.x | ✅ |

## Reporting a vulnerability

Please **do not** open a public issue for a security problem.

Report privately by email to **security@tokser.example** with:

- A description of the issue and its impact
- Steps to reproduce (proof-of-concept if possible)
- Affected version and configuration
- Any suggested remediation

You can expect:

- Acknowledgement within **3 business days**
- A triage decision within **10 business days**
- Credit in the release notes once a fix ships, unless you prefer to stay anonymous

Please give us a reasonable window to release a fix before public disclosure.

## Scope

In scope:

- Authentication and session handling
- Authorization bypass (RBAC)
- CSRF, XSS, SQL injection
- Path traversal, Zip Slip, arbitrary file read/write
- Command injection
- Credential or secret disclosure
- Server-side request forgery via storage backends

Out of scope:

- Issues requiring an already-compromised host
- Denial of service through resource exhaustion with valid admin credentials
- Reports from automated scanners without a demonstrated impact
- Social engineering

## Deployment hardening checklist

- [ ] Serve over HTTPS and set `TBM_SECURE_COOKIE=true`
- [ ] Keep `TBM_SECRET_KEY` and `TBM_ENCRYPTION_KEY` out of version control
- [ ] Restrict file permissions on `.env` (`chmod 600`)
- [ ] Set `TBM_ALLOWED_HOSTS` to your hostname
- [ ] Bind the application to `127.0.0.1` and expose it only through Nginx
- [ ] Run the service as the unprivileged `TBM` user
- [ ] Grant read access to protected paths with `sudo tbm access grant <path>` (ACL), never by running as root
- [ ] Keep the panel off the public internet, or put it behind a VPN / IP allowlist
- [ ] Enable two-factor authentication for administrators
- [ ] Review **Activity Logs** periodically
- [ ] Back up `.env` **separately** from the database

## Security design notes

- Passwords: Argon2id (bcrypt accepted for legacy hashes, re-hashed on login)
- Sessions: random 256-bit tokens, only SHA-256 hashes stored, server-side expiry
- CSRF: middleware-enforced for all cookie-authenticated mutating requests
- Secrets at rest: AES-256-GCM, key derived from `TBM_ENCRYPTION_KEY` via PBKDF2
- Archive encryption: AES-256-GCM with a unique nonce per 1 MiB chunk
- No shell execution anywhere; subprocesses use argument lists
- SQL exclusively through SQLAlchemy parameter binding
