# Contributing to DOCSight

Thanks for your interest in contributing!

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

124+ tests cover analyzers, API endpoints, config, MQTT, i18n, and PDF generation.

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
tests/               - pytest test suite (124+ tests)
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

## Guidelines

- Keep changes focused and minimal
- Add tests for new functionality
- Maintain all 4 language translations (EN/DE/FR/ES) in `app/i18n/*.json`
- CHANGELOG entries must be in English
- Run the full test suite before submitting a PR

## Adding Modem Support

DOCSight currently supports AVM FRITZ!Box Cable routers. To add support for another modem:

1. Create a new module in `app/` (e.g., `app/arris.py`)
2. Implement `login()`, `get_docsis_data()`, and `get_device_info()` matching the FritzBox API
3. Return data in the same format as `fritzbox.get_docsis_data()` so the analyzer works unchanged
4. Update `main.py` to select the modem driver based on configuration
