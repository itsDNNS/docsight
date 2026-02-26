# Security Policy

## Supported Versions

We release security updates for the following versions:

| Version | Supported          |
| ------- | ------------------ |
| v2.x (main) | :white_check_mark: |
| v1.x (legacy) | :x: (no longer supported) |

**Recommendation:** Always use the latest release from the `main` branch for the newest features and security fixes.

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

If you discover a security vulnerability in DOCSight, please report it privately:

### Preferred Method: GitHub Security Advisories

1. Go to https://github.com/itsDNNS/docsight/security/advisories
2. Click "Report a vulnerability"
3. Provide details about the vulnerability

### Alternative: Email

Send an email to the maintainer with:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if you have one)

You can find the maintainer's contact information in the GitHub profile.

## What to Expect

- **Initial Response:** Within 48 hours
- **Status Update:** Within 7 days
- **Fix Timeline:** Depends on severity
  - Critical: Emergency patch within 24-48 hours
  - High: Patch within 1-2 weeks
  - Medium/Low: Next planned release

## Security Considerations

DOCSight is designed to run **100% locally** on your network:

- No external API calls (except optional integrations you configure)
- No telemetry or analytics
- No cloud dependencies

## Security Features

### Authentication

DOCSight includes built-in authentication protecting all routes:

- **Admin password** — hashed with Werkzeug (`scrypt` or `pbkdf2`). Plaintext passwords from older versions are auto-upgraded to hashes on first login.
- **Session-based login** — browser sessions via Flask's signed cookies.
- **API tokens** — Bearer token authentication for programmatic access (see [API Token Security](#api-token-security) below).

All routes are protected by the `require_auth` decorator. Sensitive management endpoints (token creation/revocation, settings) require a session login and cannot be accessed with API tokens alone.

### Login Rate Limiting

Failed login attempts are rate-limited per IP address:

- **5 attempts** within a **15-minute** window before lockout
- **Exponential backoff** starting at 30 seconds, doubling with each additional failed attempt (30s, 60s, 120s, ... up to 7680s)
- Rate-limited login attempts are rejected with a lockout message showing the remaining wait time

Rate limit counters are stored in memory and reset on application restart.

### API Token Security

API tokens follow security best practices:

- **Cryptographically random** — generated with `secrets.token_urlsafe(48)`
- **Prefixed** — all tokens start with `dsk_` for easy identification in logs and secret scanners
- **Hash-only storage** — only a Werkzeug hash is persisted; the plaintext token is shown once at creation and never stored
- **Prefix display** — the first 8 characters (`dsk_XXXX`) are stored separately for identification in the UI
- **Last-used tracking** — each successful token use updates a `last_used_at` timestamp
- **Revocation** — tokens can be revoked instantly; revoked tokens are rejected on all subsequent requests

### Security Headers

DOCSight sets the following headers on every response:

| Header | Value |
| --- | --- |
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` |
| `Content-Security-Policy` | `default-src 'self'; script-src 'self' 'unsafe-inline' https://unpkg.com https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: blob: https:; connect-src 'self'` |
| `X-Frame-Options` | `DENY` |
| `X-Content-Type-Options` | `nosniff` |
| `X-XSS-Protection` | `1; mode=block` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |

If you run DOCSight behind a reverse proxy, the proxy does **not** need to duplicate these headers.

### Encryption at Rest

Modem credentials and other secrets are encrypted at rest using **Fernet** (AES-128-CBC + HMAC-SHA256):

- Encrypted fields: `modem_password`, `mqtt_password`, `speedtest_tracker_token`, `notify_webhook_token`
- Encryption key stored in `data/.config_key` (auto-generated on first run, file permissions set to `600`)
- The admin password is **hashed** (not encrypted) via Werkzeug and stored separately

### Audit Logging

Security-relevant events are logged to the `docsis.audit` logger:

- Login attempts (successful and failed)
- Rate-limit triggers
- Password hash auto-upgrades
- Configuration changes (with changed keys listed)
- API token creation and revocation

**Structured JSON output** can be enabled by setting `DOCSIGHT_AUDIT_JSON=1`. This produces log lines like:

```json
{"ts": "2025-01-15T10:30:00", "level": "INFO", "event": "Login successful: ip=192.168.1.10"}
```

## Running Securely

**Docker (Recommended):**
- Container runs as non-root user
- No host network mode (bridge networking)
- Data volume isolates database

**Network Exposure:**
- By default, DOCSight listens on `0.0.0.0:8765`
- For single-user setups, bind to localhost only: `-p 127.0.0.1:8765:8765`
- For LAN or remote access, use a [reverse proxy](docs/reverse-proxy.md) with HTTPS

**Modem Credentials:**
- Stored encrypted in `data/config.json` (Fernet symmetric encryption)
- Key stored in `data/.config_key` (generated on first run)
- Keep `data/` directory permissions restricted

## Known Limitations

- **In-memory rate limits** — login attempt counters are lost on restart
- **Modem credentials in memory** — required during polling cycles
- **MQTT credentials** — stored encrypted, but sent over the network to the MQTT broker (use TLS on the broker side)

## Security Best Practices

1. **Keep DOCSight updated:** Run `docker pull` regularly
2. **Restrict network access:** Use a reverse proxy with HTTPS for remote access
3. **Use strong modem passwords:** DOCSight inherits your modem's security
4. **Review audit logs:** Check `docker logs docsight` or enable JSON audit logging for structured analysis
5. **Backup your data:** `data/` directory contains all configuration and history

## Third-Party Dependencies

DOCSight uses Python libraries from PyPI. We monitor dependencies for known vulnerabilities:

- `dependabot` is enabled for automated security updates
- Review `requirements.txt` for the full list

If you discover a vulnerability in a dependency, please report it to the upstream project and open an issue here referencing it.

## Disclosure Policy

- We follow **coordinated disclosure**
- Security fixes are released as soon as possible
- Credit is given to reporters (unless they request anonymity)
- After a fix is released, details may be published in GitHub Security Advisories

Thank you for helping keep DOCSight and its users safe!
