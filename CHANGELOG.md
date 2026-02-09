# Changelog

All notable changes to this project will be documented in this file.

Versioning: `YYYY-MM-DD.N` (date + sequential build number per day)

## [2026-02-09.3]

### Added
- **Hamburger-Menu**: Sliding Sidebar mit Navigation (Live, Tagesverlauf, Wochentrend, Monatstrend, Einstellungen)
- **Kalender-Popup**: Mini-Monatskalender mit hervorgehobenen Datentagen zur Datumsnavigation
- **Trend-Charts**: Chart.js Diagramme fuer DS Power, DS SNR, US Power und Fehler (Tag/Woche/Monat)
- **API-Endpunkte**: `/api/calendar`, `/api/trends`, `/api/snapshot/daily` fuer Trend- und Kalenderdaten
- **Snapshot-Uhrzeit**: Konfigurierbarer Referenz-Zeitpunkt fuer Tagesvergleiche (Setup + Settings)

### Changed
- **Dashboard komplett ueberarbeitet**: Neue Topbar mit Hamburger, Datumsnavigation und Kalender
- **Timeline-Navigation ersetzt**: Kalender-Popup statt Dropdown-Select fuer historische Snapshots

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
