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
- Construct applications only with `app.app_factory.create_app()`. Importing `app.web` must remain free of application construction and app-specific globals.

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for detailed technical documentation and data flow diagrams.

## Development Setup

```bash
git clone https://github.com/itsDNNS/docsight.git
cd docsight
python -m pip install --require-hashes -r requirements.txt
python -m pip install --require-hashes -r requirements-test.txt
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
  app_factory.py     - Deterministic Flask application construction
  main.py            - Entrypoint, ThreadPoolExecutor polling loop
  runtime.py         - Typed per-application runtime state and locks
  web.py             - Core routes, filters, auth, and runtime accessors
  analyzer.py        - DOCSIS channel health analysis
  threshold_profiles.py - Built-in analyzer threshold profiles
  event_detector.py  - Signal anomaly detection (thread-safe)
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

Translations live in `app/i18n/` as JSON files. The core interface has a 24-language European language pack; built-in modules keep `en.json` source catalogs and fall back to English unless a module explicitly ships its own locale file.

Each core locale file has a `_meta` field with `language_name` and `flag`. When adding or changing core UI strings, update **all existing core language files**. When adding or changing module UI strings, update the module's `en.json` source catalog and rely on English fallback unless the module intentionally owns a translated catalog.

### Adding a New Language

DOCSight is used internationally and translations from native speakers are welcome. To add a new core language:

1. Run `python scripts/i18n_check.py --generate` to create `app/i18n/template.json` locally from the current English source catalog.
2. Copy the generated file to `app/i18n/<lang>.json` (e.g. `sv.json` for Swedish, `nl.json` for Dutch). Use the ISO 639-1 two-letter code.
3. Fill in `_meta.language_name` (native spelling, e.g. `Svenska` not `Swedish`) and `_meta.flag` (emoji flag).
4. Translate the values. Keep the JSON keys untouched. Preserve any `{placeholder}` tokens in the strings.
5. Run `python scripts/i18n_check.py --validate` to make sure no keys are missing or extra compared to `en.json`.
6. Open a PR. Mention in the description whether you are able to keep the translation updated when new strings are added in the future.

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

Server-side module code should import the established accessors it needs from
`app.web`, such as `get_config_manager()`, `get_storage()`, `get_state()`, or
`get_module_loader()`. These accessors resolve the active application's typed
runtime. Do not import or create a module-level Flask application, and do not
cache app-derived storage or mutable request/runtime state in module globals.
Collectors receive their runtime-facing `web` object explicitly and must keep
working without a Flask application context.

### Browser URL contract

DOCSight may be mounted below a reverse-proxy path such as `/docsight`. Browser code in core and community modules must pass every app-owned root-relative URL through `window.docsightUrl(path)` at the point where it is used. This includes `fetch()` targets, constructed API URLs, generated `href`/`src` attributes, downloads, and internal navigation:

```javascript
fetch(docsightUrl('/api/example'));
image.src = docsightUrl('/api/example/image/' + id);
```

The helper is loaded before module scripts on DOCSight's standalone pages. It accepts only a safe internal string beginning with exactly one `/`, preserves query strings and fragments, and throws for relative, absolute, protocol-relative, traversal, malformed, or ambiguously encoded input. Modules should not catch that error and retry with an unprefixed URL.

Keep server-rendered Jinja URLs on `url_for()` or `module_static_url()`. External links, `blob:`/`data:` URLs, and current-document query/hash navigation do not use `docsightUrl()`. Do not patch browser globals such as `fetch` or `location`, and do not copy or infer the deployment prefix in module code.

See the **[DOCSight Community Modules](https://github.com/itsDNNS/docsight-modules)** repository for the development guide, starter template, and submission process.

## Adding Modem Support

See the **[Adding Modem Support](https://github.com/itsDNNS/docsight/wiki/Adding-Modem-Support)** wiki page for the full guide, including raw data format, analyzer output reference, and wanted drivers.
