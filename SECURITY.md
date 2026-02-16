# Security Policy

## Supported Versions

We release security updates for the following versions:

| Version | Supported          |
| ------- | ------------------ |
| v2.x (main) | :white_check_mark: |
| v2-dev (feature branches) | :white_check_mark: |
| v1.x (legacy) | :x: (maintenance mode) |

**Recommendation:** Always use the latest release from the `main` branch or `v2-dev` for the newest features and security fixes.

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
- Credentials encrypted at rest (AES-128)

### Running Securely

**Docker (Recommended):**
- Container runs as non-root user
- No host network mode (bridge networking)
- Data volume isolates database

**Network Exposure:**
- By default, DOCSight listens on `0.0.0.0:8765`
- For single-user setups, bind to localhost only: `-p 127.0.0.1:8765:8765`
- For LAN access, use a reverse proxy (nginx, Traefik) with HTTPS

**Modem Credentials:**
- Stored encrypted in `data/config.json` (Fernet symmetric encryption)
- Key derived from `data/SECRET_KEY` (generated on first run)
- Keep `data/` directory permissions restricted

**Optional Authentication:**
- DOCSight has no built-in authentication (designed for single-user/LAN)
- Use a reverse proxy with HTTP Basic Auth or OAuth if exposing to the internet

## Known Limitations

- **No built-in user authentication:** Use a reverse proxy if needed
- **Modem credentials in memory:** Required for polling, cleared after use
- **MQTT credentials:** Stored encrypted, sent over network to MQTT broker

## Security Best Practices

1. **Keep DOCSight updated:** Run `docker pull` regularly
2. **Restrict network access:** Don't expose port 8765 to the internet without authentication
3. **Use strong modem passwords:** DOCSight inherits your modem's security
4. **Review logs:** Check `docker logs docsight` for suspicious activity
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
