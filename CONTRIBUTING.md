# Contributing to DOCSight

Thanks for your interest in contributing!

## Development Setup

```bash
git clone https://github.com/itsDNNS/docsight.git
cd docsight
pip install -r requirements.txt
pip install pytest
```

## Running Tests

```bash
python -m pytest tests/ -v
```

## Running Locally

```bash
python -m app.main
```

Open `http://localhost:8765` to access the setup wizard.

## Project Structure

```
app/
  main.py          - Entrypoint, polling loop, thread management
  web.py           - Flask routes and API endpoints
  analyzer.py      - DOCSIS channel health analysis
  fritzbox.py      - FritzBox data.lua API client
  config.py        - Configuration management (env + config.json)
  storage.py       - SQLite snapshot storage
  mqtt_publisher.py - MQTT Auto-Discovery for Home Assistant
  i18n.py          - Translation strings (EN/DE)
  templates/       - Jinja2 HTML templates
tests/             - pytest test suite
```

## Guidelines

- Keep changes focused and minimal
- Add tests for new functionality
- Maintain English and German translations in `app/i18n.py`
- CHANGELOG entries must be in English
- Run the full test suite before submitting a PR

## Adding Modem Support

DOCSight currently supports AVM FRITZ!Box Cable routers. To add support for another modem:

1. Create a new module in `app/` (e.g., `app/arris.py`)
2. Implement `login()`, `get_docsis_data()`, and `get_device_info()` matching the FritzBox API
3. Return data in the same format as `fritzbox.get_docsis_data()` so the analyzer works unchanged
4. Update `main.py` to select the modem driver based on configuration
