# Changelog

All notable changes to this project will be documented in this file.

Versioning: `YYYY-MM-DD.N` (date + sequential build number per day)

## [2026-02-09.8]

### Changed
- **ISP selection**: Dropdown with common German cable ISPs + "Other" option with free text input

## [2026-02-09.7]

### Added
- **ISP name field**: Configurable in Setup and Settings, included in LLM export report

### Fixed
- **Clipboard copy**: Fixed copy-to-clipboard on non-HTTPS connections (fallback to `execCommand`)

## [2026-02-09.6]

### Added
- **LLM Export**: Generate structured markdown report for AI analysis (ChatGPT, Claude, Gemini, etc.)
- **Export modal**: Copy-to-clipboard dialog accessible from sidebar menu
- **API endpoint**: `/api/export` returns full DOCSIS status report with context and reference values

## [2026-02-09.5]

### Added
- **Internationalization (i18n)**: English as default language, German available via toggle
- **Language selector**: Configurable in Setup (top-right) and Settings (General section)
- **Sortable table columns**: Click any column header to sort ascending/descending
- **Compact error formatting**: Large numbers abbreviated with k suffix (e.g. 132k, 5.9k)

## [2026-02-09.4]

### Changed
- **Channel tables grouped by DOCSIS version**: Collapsible sections for DOCSIS 3.1 and 3.0 channels
- **Reference table moved to sidebar**: Accessible via expandable "Richtwerte" section in hamburger menu
- **DOCSIS column removed**: Redundant with group headers, saves horizontal space

## [2026-02-09.3]

### Added
- **Hamburger menu**: Sliding sidebar with navigation (Live, Day trend, Week trend, Month trend, Settings)
- **Calendar popup**: Mini month calendar with highlighted data days for date navigation
- **Trend charts**: Chart.js diagrams for DS Power, DS SNR, US Power and Errors (day/week/month)
- **API endpoints**: `/api/calendar`, `/api/trends`, `/api/snapshot/daily` for trend and calendar data
- **Snapshot time**: Configurable reference time for daily comparisons (Setup + Settings)

### Changed
- **Dashboard redesigned**: New topbar with hamburger, date navigation and calendar
- **Timeline navigation replaced**: Calendar popup instead of dropdown select for historical snapshots

## [2026-02-09.2]

### Added
- **Setup Wizard**: Browser-based first-time configuration at `/setup`
- **Settings Page**: Runtime configuration at `/settings` with light/dark mode toggle
- **Config Persistence**: Settings stored in `config.json` (Docker volume), survives restarts
- **Environment Variable Overrides**: Env vars take precedence over config.json
- **Password Encryption**: Credentials encrypted at rest with Fernet (AES-128)
- **Connection Tests**: "Test connection" buttons for FritzBox and MQTT in setup/settings
- **CI/CD**: GitHub Actions auto-builds Docker image to GHCR on push
- **Light/Dark Mode**: Theme toggle in settings, persisted via config + localStorage

### Changed
- **MQTT is now optional**: App runs web-only without MQTT configuration
- **No crash without credentials**: Container starts and shows setup wizard instead of exiting
- **Poll interval configurable in setup**: Min 60s, max 3600s
- **Secrets removed from tracked files**: docker-compose.yml contains no credentials

## [2026-02-09.1]

### Added
- DOCSIS channel monitoring via FritzBox `data.lua` API
- Per-channel sensors (~37 DS + 4 US) via MQTT Auto-Discovery
- 14 summary sensors (power, SNR, errors, health)
- Health assessment with traffic-light evaluation (Gut/Grenzwertig/Schlecht)
- Web dashboard with auto-refresh and timeline navigation
- SQLite snapshot storage with configurable retention
- PBKDF2 authentication for modern FritzOS (MD5 fallback for legacy)
