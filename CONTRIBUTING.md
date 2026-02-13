# Contributing to DOCSight

Thanks for your interest in contributing!

## Before You Start

**Please open an issue first** before working on any new feature or significant change. This lets us discuss the approach and make sure it fits the project architecture. PRs without a prior issue may be closed.

This is especially important for:
- New features or modules
- Architectural changes
- Changes touching multiple files

Small bugfixes and typo corrections are fine without an issue.

## Architecture

DOCSight uses a single data flow pipeline. All data follows this path:

```
Modem (fritzbox.py) → Analyzer (analyzer.py) → Event Detector (event_detector.py)
  → Storage (storage.py) → Web UI (web.py) / Reports (report.py)
```

**When contributing, your code must integrate into this pipeline.** Do not create parallel subsystems with separate storage, threading, or state management. New data sources should hook into the existing polling loop in `main.py`.

See the [v2.0 Milestone](https://github.com/itsDNNS/docsight/milestone/1) for the planned Unified Collector Architecture ([#23](https://github.com/itsDNNS/docsight/issues/23)) that will formalize this pattern.

## Development Setup

```bash
git clone https://github.com/itsDNNS/docsight.git
cd docsight
pip install -r requirements.txt
pip install pytest
```

## Docker Development

For a containerized dev environment:

```bash
docker compose -f docker-compose.dev.yml up -d --build
```

This runs on port **8766** (`http://localhost:8766`). Production uses `docker-compose.yml` on port 8765.

## Running Tests

```bash
python -m pytest tests/ -v
```

196 tests cover analyzers, event detection, API endpoints, config, MQTT, i18n, and PDF generation. All tests must pass before submitting a PR.

## Running Locally

```bash
python -m app.main
```

Open `http://localhost:8765` to access the setup wizard.

## Project Structure

```
app/
  main.py            - Entrypoint, polling loop, thread management
  web.py             - Flask routes and API endpoints
  analyzer.py        - DOCSIS channel health analysis
  event_detector.py  - Signal anomaly detection (power, SNR, modulation changes)
  thresholds.json    - Configurable signal thresholds (VFKD guidelines)
  fritzbox.py        - FritzBox data.lua API client
  config.py          - Configuration management (env + config.json)
  storage.py         - SQLite snapshot storage
  mqtt_publisher.py  - MQTT Auto-Discovery for Home Assistant
  report.py          - Incident Report PDF generator (fpdf2)
  thinkbroadband.py  - BQM integration
  i18n/              - Translation files (EN/DE/FR/ES JSON)
  fonts/             - Bundled DejaVu fonts for PDF generation
  static/            - Static assets (icons, etc.)
  templates/         - Jinja2 HTML templates
  changelog.json     - Release changelog for splash modal
tests/               - pytest test suite (196 tests)
docker-compose.yml     - Production Docker setup
docker-compose.dev.yml - Development Docker setup (port 8766)
```

## Internationalization (i18n)

Translations live in `app/i18n/` as JSON files:

- `en.json` — English
- `de.json` — German
- `fr.json` — French
- `es.json` — Spanish

Each file has a `_meta` field with `language_name` and `flag`. When adding or changing UI strings, update **all 4 files**.

## Pull Request Guidelines

- **One PR per feature/fix.** Don't bundle unrelated changes.
- **Keep changes focused and minimal.** Smaller PRs are easier to review and more likely to be merged.
- **Follow the pipeline architecture.** New functionality must integrate into the existing data flow, not bypass it.
- Add tests for new functionality
- Maintain all 4 language translations (EN/DE/FR/ES) in `app/i18n/*.json`
- Run the full test suite before submitting a PR
- AI-generated bulk PRs without prior discussion will not be merged

## Adding Modem Support

See the **[Adding Modem Support](https://github.com/itsDNNS/docsight/wiki/Adding-Modem-Support)** wiki page for the full guide, including raw data format, analyzer output reference, and wanted drivers.
