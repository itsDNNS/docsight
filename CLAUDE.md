# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Repo:** https://github.com/itsDNNS/docsight

DOCSight is a Python web application that monitors cable internet (DOCSIS) signals from AVM FritzBox routers 24/7, collecting evidence for ISP complaints. It runs entirely locally with no cloud dependencies.

**Stack:** Python 3.12+ / Flask / SQLite / Jinja2 / vanilla JS frontend / paho-mqtt

## Commands

```bash
# Run locally
python -m app.main

# Run tests (192 tests)
python -m pytest tests/ -v

# Run a single test
python -m pytest tests/test_analyzer.py::TestHealthGood::test_all_normal -v

# Docker dev (port 8766)
docker compose -f docker-compose.dev.yml up -d --build

# Install dependencies
pip install -r requirements.txt
pip install pytest
```

No linter or formatter is configured.

## Architecture

**Threading model:** `main.py` runs two threads — a polling loop (collects FritzBox data at configurable intervals) and a Flask/Waitress web server (default port 8765). The main thread idles and listens for shutdown via `threading.Event`.

**Data flow:**
```
FritzBox modem → fritzbox.py (HTTP/login.lua)
  → analyzer.py (health assessment per channel using thresholds.json)
  → event_detector.py (stateful anomaly detection between snapshots)
  → storage.py (SQLite persistence)
  → mqtt_publisher.py (Home Assistant Auto-Discovery)
  → web.py (Flask API + dashboard)
  → report.py (PDF incident reports via fpdf2)
```

**Config precedence:** Environment variables > `/data/config.json` > hardcoded defaults. Secrets (passwords, tokens) are encrypted at rest with Fernet (AES-128-CBC). The encryption key lives at `/data/.config_key`.

**Signal thresholds** in `app/thresholds.json` are per-modulation (64QAM/256QAM/1024QAM) and per-DOCSIS-version, based on Vodafone Kabel Deutschland guidelines. The analyzer produces health statuses: Good/Marginal/Poor/Critical.

## Key Conventions

- **i18n:** All user-facing strings use translation files in `app/i18n/` (en.json, de.json, fr.json, es.json). When adding or changing UI strings, update **all 4 files**. Each has a `_meta` field with `language_name` and `flag`.
- **Adding modem support:** Create a new module in `app/` implementing `login()`, `get_docsis_data()`, and `get_device_info()` matching the FritzBox API return format so the analyzer works unchanged.
- **Storage:** SQLite database at `/data/docsis_history.db`. Tables: snapshots, bqm_graphs, speedtest_results, incidents, incident_attachments, events. Attachments stored as BLOBs (max 10 MB each, max 10 per incident).
- **Frontend:** The dashboard is a single large Jinja2 template (`app/templates/index.html`, ~174 KB) with vanilla JavaScript. No frontend build step.

## Workflow & Process

**Role:** You are the **Lead Developer** (implementation). Nova (OpenClaw) is your PM/QA.

1. **Branching:**
   - ALWAYS work on `dev` branch.
   - NEVER commit directly to `main` (protected for releases).

2. **Definition of Done:**
   - All tests passed (`python -m pytest tests/ -v`).
   - If UI changed: i18n keys added to **all 4 languages** (en/de/fr/es).
   - If UI changed: Mobile responsiveness verified (in thought/code).
   - Code committed to `dev` with a clear message (e.g., `Add channel timeline feature`).

3. **Handoff (Wake Nova):**
   - When you are finished with a task and have committed to `dev`:
   - Run: `openclaw system event --text "Done: <summary of changes>" --mode now`
   - This wakes up Nova (PM/QA) to perform acceptance testing and release prep.

4. **Releases:**
   - Do NOT create tags or releases yourself. Nova manages the release cycle.

## Emergency / User Override

If Nova is offline or the user explicitly takes command:
- You may perform releases if instructed: Merge `dev` -> `main`, tag `vYYYY-MM-DD.N`.
- ALWAYS run full test suite before tagging.
- Check `gh release list` first to ensure the next version number is free.
- You become responsible for QA (self-verify thoroughly).
