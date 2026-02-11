# Changelog

All notable changes to this project will be documented in this file.

Versioning: `YYYY-MM-DD.N` (date + sequential build number per day)

## [2026-02-11.19]

### Added
- **Incident Report Export**: Two-step flow — editable ISP complaint letter with customer data fields + downloadable technical PDF report with channel tables, worst values, and DIN threshold references
- **Report i18n**: Full PDF report localization in 4 languages (EN/DE/FR/ES) with locale-appropriate regulatory authorities (Bundesnetzagentur, ARCEP, etc.)
- **Language selector in topbar**: Country flag dropdown (🇬🇧🇩🇪🇫🇷🇪🇸) for quick language switching
- **BQM setup guide**: Sidebar link always visible; when not configured, opens modal with benefits and step-by-step setup instructions (DynDNS, WAN ping, ThinkBroadband registration)
- **Bundled DejaVu fonts**: PDF generation works in Docker without host font dependencies

### Changed
- **Settings moved to sidebar bottom**: Following common UI convention
- **Report modal redesign**: Split into complaint letter (copyable text) + technical report (PDF attachment) for easier ISP communication

### Fixed
- **BQM modal HTML rendering**: i18n strings with HTML tags now render correctly via Jinja2 safe filter

## [2026-02-09.18]

### Added
- **AJAX live refresh**: Dashboard updates every 60s without full page reload — open modals, expanded metric cards, and channel groups are preserved
- **Dark/Light theme toggle**: Quick-switch button in the topbar corner with persistent localStorage preference
- **Modem uptime display**: Errors card now shows device uptime (days + hours)
- **Range indicators**: Colored good/warn/crit zone bars with value marker for DS Power, SNR, and US Power
- **Channel group health badges**: Collapsed DOCSIS version groups show green checkmark or warning/critical count
- **DOCSIS 3.1 upstream warning**: Notice when no OFDMA upstream channel is detected

### Changed
- **Dashboard redesign**: Replaced 7 flat summary tiles with connection info bar + 3 compact metric cards (Downstream, Upstream, Errors) with progressive disclosure
- **DOCSIS version sorting**: Channel groups now correctly sort descending (4.0, 3.1, 3.0)

### Fixed
- **Card expand bug**: Clicking anywhere on a card no longer expands all cards — only the header is clickable
- **Card height alignment**: Cards no longer stretch to match the tallest card in the row

## [2026-02-09.17]

### Added
- **ThinkBroadband BQM integration**: Daily fetch and archive of broadband quality monitor graphs (latency, packet loss)
- **BQM gallery view**: New sidebar view to browse archived BQM graphs with date navigation and calendar integration
- **BQM configuration**: `BQM_URL` env var and settings/setup UI field for the BQM share URL
- **BQM API endpoints**: `GET /api/bqm/dates` and `GET /api/bqm/image/<date>` for graph retrieval
- **BQM translations**: EN, DE, FR, ES support for all BQM-related UI strings

## [2026-02-09.16]

### Added
- **French translation** (Français): Full UI localization with SFR as cable ISP option
- **Spanish translation** (Español): Full UI localization with Vodafone, Euskaltel, R, Telecable as cable ISP options
- **Installation guide** (`INSTALL.md`): Step-by-step beginner guide with 4 install methods (Docker CLI, Compose, Portainer, Dockhand), setup wizard walkthrough, troubleshooting, and uninstall instructions
- **Timezone-aware snapshot hint**: Setup and settings show converted local time next to server timezone for daily snapshot scheduling
- **Dedicated user recommendation**: Setup wizard and install guide recommend creating a separate modem user for DOCSight

### Changed
- **i18n modularized**: Translations moved from single Python file to `app/i18n/` package with per-language JSON files — adding a new language now only requires dropping a `.json` file
- **Poll interval default**: Changed from 5 minutes (300s) to **15 minutes** (900s)
- **Poll interval maximum**: Increased from 1 hour (3600s) to **4 hours** (14400s)
- **History default**: Changed to unlimited (0 = keep all snapshots)
- **Documentation generalized**: Replaced FRITZ!Box-specific references with modem-agnostic wording throughout README and INSTALL
- **Environment variable rename**: `FRITZ_*` env vars deprecated in favor of `MODEM_*` (old vars still work as fallback)
- **Config key migration**: Old `fritz_*` keys in config.json automatically migrated to `modem_*` on load

## [2026-02-09.15] - Initial Public Release

### Added
- **DOCSight icon**: Favicon, sidebar logo, login/setup branding, README header
- **README screenshots**: Dashboard (dark/light), setup wizard, trend charts, health banner
- **Docker entrypoint**: Automatic data volume permission handling for upgrades

### Changed
- **UI labels generalized**: "FritzBox Connection" renamed to "Modem Connection" (EN/DE) for future multi-modem support

## [2026-02-09.14]

### Changed
- **Password hashing**: Admin password stored as scrypt hash instead of reversible encryption
- **Session key persisted**: Flask session secret key saved to file, sessions survive container restarts
- **All API endpoints require auth**: `/api/calendar`, `/api/trends`, `/api/export`, `/api/snapshots`, `/api/snapshot/daily` now protected
- **Input validation**: Timestamp and date parameters validated against format regex
- **Security headers**: `X-Content-Type-Options`, `X-Frame-Options`, `X-XSS-Protection`, `Referrer-Policy` on all responses
- **Non-root Docker user**: Container runs as `appuser` (uid 1000) instead of root

## [2026-02-09.13]

### Added
- **Web UI authentication**: Optional admin password protects all routes except `/health`; configurable in Settings
- **Login page**: Clean login form with i18n support (EN/DE)
- **Logout**: Session-based auth with logout link in sidebar
- **CONTRIBUTING.md**: Guidelines for contributors and modem driver development

## [2026-02-09.12]

### Added
- **MIT License**: Added LICENSE file
- **Test suite**: 70 tests covering analyzer, config, storage, and web routes
- **Production web server**: Replaced Flask dev server with Waitress
- **Docker healthcheck**: Container reports health via `/health` endpoint
- **Screenshot placeholders in README**: Gallery structure for dashboard, setup, trends, health banner

## [2026-02-09.11]

### Changed
- **Project renamed to DOCSight**: Removed FritzBox trademark from project name, repo, Docker image, MQTT identifiers
- **MQTT entities renamed**: `fritzbox_docsis_*` → `docsight_*`, device name now "DOCSight"
- **Default MQTT topic prefix**: Changed from `fritzbox/docsis` to `docsight`

## [2026-02-09.10]

### Changed
- **Health status redesigned**: Informative banner with translated status, explanation, and per-issue descriptions with actionable recommendations
- **Analyzer outputs English keys**: Health uses `good/marginal/poor`, issues are machine-readable keys translated in the UI
- **Channel groups collapsed by default**: Less visual clutter, expand to inspect

## [2026-02-09.9]

### Added
- **Tariff display**: ISP name and max down/up speeds (from FritzBox) shown on dashboard
- **Connection info API**: Fetches max downstream/upstream speeds from FritzBox `netMoni` page

### Changed
- **Sidebar always visible**: Persistent left panel with collapse toggle instead of overlay
- **Gear icon removed**: Settings accessible via sidebar only

### Fixed
- **ISP "Other" field alignment**: Manual input field now properly aligned in grid layout

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
