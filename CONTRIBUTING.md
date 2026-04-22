# Contributing to DOCSight

Thanks for your interest in contributing.

If you need setup help, troubleshooting, or want to share a real-world DOCSight deployment, start with [SUPPORT.md](SUPPORT.md) so you end up in the right place first.

## Before You Start

**Please open an issue or start an Ideas discussion first** before working on any new feature or significant change. This lets us discuss the approach and make sure it fits the project architecture. PRs without prior discussion may be closed.

This is especially important for:
- New features or modules
- Architectural changes
- Changes touching multiple files

Small bugfixes and typo corrections are fine without an issue.

## Architecture

DOCSight v2.0 uses a **modular collector-based architecture**. All data collection follows this pattern:

```
Collector Registry → Base Collector (Fail-Safe) → Analyzer/Storage → Web UI
```

**When contributing:**
- New data sources must implement the `Collector` base class
- New modem types must implement the `ModemDriver` base class (`app/drivers/base.py`)
- Collectors run in **parallel threads** via `ThreadPoolExecutor`. Protect shared state with locks.
- Use the collector pattern for automatic fail-safe and health monitoring

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for detailed technical documentation and data flow diagrams.

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

This runs on port **8767** (`http://localhost:8767`) in demo mode. Production uses `docker-compose.yml` on port 8765.

## Running Tests

```bash
python -m pytest tests/ -v
```

The test suite covers analyzers, collectors, drivers, event detection, API endpoints, config, MQTT, i18n, and PDF generation. All tests must pass before submitting a PR.

## Running Locally

```bash
python -m app.main
```

Open `http://localhost:8765` to access the setup wizard.

## Project Structure

```
app/
  main.py            - Entrypoint, ThreadPoolExecutor polling loop
  web.py             - Flask routes and API endpoints (thread-safe state)
  analyzer.py        - DOCSIS channel health analysis
  event_detector.py  - Signal anomaly detection (thread-safe)
  thresholds.json    - Configurable signal thresholds (VFKD guidelines)
  config.py          - Configuration management (env + config.json)
  storage/           - SQLite storage (base + mixins), WAL mode, thread-safe
  collectors/        - Collector implementations (modem, demo, speedtest, bqm)
    base.py          - Abstract Collector with fail-safe and locking
    __init__.py      - Registry and discover_collectors()
  drivers/           - Modem driver implementations for the supported hardware families
    base.py          - Abstract ModemDriver interface
    registry.py      - Driver registry (auto-detection + manual selection)
  modules/           - Built-in modules (backup, bnetz, bqm, journal, mqtt, ...)
  blueprints/        - Flask blueprints (config, polling, data, analysis, ...)
  i18n/              - Translation files (EN/DE/FR/ES JSON)
  fonts/             - Bundled DejaVu fonts for PDF generation
  static/            - Static assets (icons, etc.)
  templates/         - Jinja2 HTML templates
tests/               - pytest test suite
docker-compose.yml     - Production Docker setup
docker-compose.dev.yml - Development Docker setup
```

## Internationalization (i18n)

Translations live in `app/i18n/` as JSON files:

- `en.json` - English
- `de.json` - German
- `fr.json` - French
- `es.json` - Spanish

Each file has a `_meta` field with `language_name` and `flag`. When adding or changing UI strings, update **all existing language files**.

### Adding a New Language

DOCSight is used internationally and translations from native speakers are welcome. To add a new language:

1. Copy `app/i18n/template.json` to `app/i18n/<lang>.json` (e.g. `sv.json` for Swedish, `nl.json` for Dutch). Use the ISO 639-1 two-letter code.
2. Fill in `_meta.language_name` (native spelling, e.g. `Svenska` not `Swedish`) and `_meta.flag` (emoji flag).
3. Translate the values. Keep the JSON keys untouched. Preserve any `{placeholder}` tokens in the strings.
4. Run `python scripts/i18n_check.py --validate` to make sure no keys are missing or extra compared to `en.json`.
5. Open a PR. Mention in the description whether you are able to keep the translation updated when new strings are added in the future.

We prefer new languages to be contributed by people who actually use the tool in that language, so the translation sounds natural and stays maintained over time. Partial translations are fine - missing keys fall back to English automatically.

## Pull Request Guidelines

- **One PR per feature/fix.** Don't bundle unrelated changes.
- **Keep changes focused and minimal.** Smaller PRs are easier to review and more likely to be merged.
- **Follow the pipeline architecture.** New functionality must integrate into the existing data flow, not bypass it.
- Add tests for new functionality
- Maintain all existing language translations in `app/i18n/*.json` (run `python scripts/i18n_check.py --validate`)
- Run the full test suite before submitting a PR
- AI-generated bulk PRs without prior discussion will not be merged

## Building Modules

DOCSight supports community modules that extend functionality without modifying core code. Modules can add API endpoints, data collectors, settings panels, dashboard tabs, and more.

See the **[DOCSight Community Modules](https://github.com/itsDNNS/docsight-modules)** repository for the development guide, starter template, and submission process.

## Adding Modem Support

See the **[Adding Modem Support](https://github.com/itsDNNS/docsight/wiki/Adding-Modem-Support)** wiki page for the full guide, including raw data format, analyzer output reference, and wanted drivers.
