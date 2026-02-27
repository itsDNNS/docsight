# DOCSight Module System — Design Document

## Goal

Transform DOCSight from a monolithic application into a modular, community-extensible platform. Anyone can build and share modules (features, integrations, themes, drivers) without modifying core code.

## Architecture

Manifest-first auto-discovery. Each module is a folder with a `manifest.json` that declares what it contributes. The core scans two directories on startup:

- `app/modules/` — built-in modules (shipped with Docker image)
- `/modules/` — community modules (volume-mounted)

Distribution is git-based: a central `docsight-modules` GitHub repo serves as the marketplace registry.

## Manifest Format

```json
{
  "id": "docsight.weather",
  "name": "Weather Overlay",
  "description": "Temperature overlay on signal charts via Open-Meteo API",
  "version": "1.0.0",
  "author": "DOCSight Team",
  "homepage": "https://github.com/itsDNNS/docsight",
  "license": "MIT",
  "minAppVersion": "2026.2",
  "type": "integration",
  "contributes": {
    "collector": "collector.py:WeatherCollector",
    "routes": "routes.py",
    "settings": "templates/settings.html",
    "tab": "templates/tab.html",
    "card": "templates/card.html",
    "i18n": "i18n/",
    "static": "static/"
  },
  "config": {
    "weather_enabled": false,
    "weather_latitude": "",
    "weather_longitude": ""
  },
  "menu": {
    "label_key": "weather.name",
    "icon": "thermometer",
    "order": 50
  }
}
```

### Manifest Fields

| Field | Required | Description |
|-------|----------|-------------|
| `id` | Yes | Unique identifier. `docsight.*` = built-in, anything else = community |
| `name` | Yes | Human-readable display name |
| `description` | Yes | Short description |
| `version` | Yes | Semantic version |
| `author` | Yes | Author name |
| `homepage` | No | URL to project/repo |
| `license` | No | License identifier |
| `minAppVersion` | Yes | Minimum DOCSight version required |
| `type` | Yes | One of: `driver`, `integration`, `analysis`, `theme` |
| `contributes` | Yes | What the module provides (all sub-fields optional) |
| `config` | No | Default config values (registered in ConfigManager) |
| `menu` | No | Sidebar menu entry (label_key, icon, order) |

### Contributes Sub-Fields

| Field | Description |
|-------|-------------|
| `collector` | `filename.py:ClassName` — data collector inheriting from Collector ABC |
| `routes` | `filename.py` — Flask Blueprint (must export `blueprint` or `bp`) |
| `settings` | `path/to/template.html` — Jinja2 fragment for Settings page |
| `tab` | `path/to/template.html` — Jinja2 fragment for dashboard tab |
| `card` | `path/to/template.html` — Jinja2 fragment for dashboard card |
| `i18n` | `directory/` — contains `en.json`, `de.json`, etc. |
| `static` | `directory/` — mounted at `/modules/<id>/static/` |

## Module Folder Structure

Full module:
```
weather/
  manifest.json
  collector.py
  routes.py
  templates/
    settings.html
    tab.html
    card.html
  static/
    weather.js
    weather.css
  i18n/
    en.json
    de.json
```

Minimal module (API only):
```
pingtest/
  manifest.json
  routes.py
```

Theme module:
```
midnight-blue/
  manifest.json
  static/
    theme.css
```

## Module Loader

`app/module_loader.py` — runs at app startup:

1. **Scan** — find all `manifest.json` in `app/modules/*/` and `/modules/*/`
2. **Validate** — check schema, required fields, `minAppVersion`, detect ID conflicts
3. **Filter** — skip modules listed in `config.json → disabled_modules[]`
4. **Load** — for each enabled module:
   - `contributes.collector` → import class, register with collector system
   - `contributes.routes` → import Blueprint, mount under `/api/modules/<id>/`
   - `contributes.settings` → register template path for Settings page
   - `contributes.tab` → register template path for dashboard tab
   - `contributes.card` → register template path for dashboard card
   - `contributes.i18n` → merge JSON files into i18n system under module namespace
   - `contributes.static` → mount directory at `/modules/<id>/static/`
   - `config` → register defaults in ConfigManager

**Error handling:** Each module loads in try/except. A broken community module never crashes the core. Errors are logged and the module is skipped.

**Module Status API:**
- `GET /api/modules` → list all modules with status
- `POST /api/modules/<id>/enable` → enable a module
- `POST /api/modules/<id>/disable` → disable a module

## Frontend Integration

### Sidebar (dynamic menu)
```html
{% for mod in modules if mod.tab %}
  <div class="nav-item" onclick="switchView('mod_{{ mod.id }}')">
    <span class="icon">{{ mod.menu.icon }}</span>
    <span>{{ T[mod.menu.label_key] }}</span>
  </div>
{% endfor %}
```

### Dashboard Tabs
```html
{% for mod in modules if mod.tab %}
  <div id="view-mod_{{ mod.id }}" class="view-panel" style="display:none">
    {% include mod.tab_path %}
  </div>
{% endfor %}
```

### Dashboard Cards
```html
<div class="module-cards">
  {% for mod in modules if mod.card %}
    {% include mod.card_path %}
  {% endfor %}
</div>
```

### Settings Tabs
```html
{% for mod in modules if mod.settings %}
  <div class="settings-tab" id="settings-{{ mod.id }}">
    <h3>{{ mod.name }}</h3>
    {% include mod.settings_path %}
  </div>
{% endfor %}
```

### Module JS/CSS (loaded only when module is active)
```html
{% for mod in modules if mod.static %}
  <link rel="stylesheet" href="/modules/{{ mod.id }}/static/{{ mod.id }}.css">
  <script src="/modules/{{ mod.id }}/static/{{ mod.id }}.js"></script>
{% endfor %}
```

Module templates have access to `T` (translations), `config`, `theme` — same variables as core templates.

## Migration: Existing Features → Built-in Modules

| Feature | Module ID | Contributes | Current Code |
|---------|-----------|-------------|--------------|
| Weather | `docsight.weather` | collector, routes, settings, i18n | `app/weather.py`, `integrations_bp.py` |
| Speedtest | `docsight.speedtest` | collector, routes, tab, settings, i18n | `app/speedtest.py`, `integrations_bp.py` |
| BQM | `docsight.bqm` | collector, routes, tab, settings, i18n | `app/bqm.py`, `integrations_bp.py` |
| BNetzA | `docsight.bnetz` | collector, routes, tab, settings, i18n | `app/bnetz*.py`, `integrations_bp.py` |
| Journal | `docsight.journal` | routes, tab, i18n | `journal_bp.py`, `journal.js` |
| Events | `docsight.events` | routes, tab, i18n | `events_bp.py`, `events.js` |
| MQTT | `docsight.mqtt` | collector, settings, i18n | `app/mqtt_publisher.py` |
| Backup | `docsight.backup` | routes, settings, i18n | `backup_bp.py` |
| Reports | `docsight.reports` | routes, i18n | `reports_bp.py`, `app/report.py` |
| Correlation | `docsight.correlation` | tab, i18n | `correlation.js` |

### What stays Core
- Modem polling + driver system
- Storage layer (SQLite)
- Dashboard (live view: channels, health, donuts)
- Signal Trends (4 charts)
- Config system + auth
- i18n framework
- Module Loader itself

### Migration Strategy
Incremental. Build the framework first, then migrate one pilot module (Weather — small, well-isolated), then the rest one by one.

## Community Marketplace

A `docsight-modules` GitHub repo serves as the central catalog:

```
github.com/itsDNNS/docsight-modules/
  registry.json
  README.md              # "How to submit your module"
  TEMPLATE/              # Starter template for new modules
    manifest.json
    routes.py
    README.md
```

### registry.json
```json
{
  "modules": [
    {
      "id": "community.pingtest",
      "name": "Ping Test",
      "description": "Monitor latency to configurable endpoints",
      "author": "community-user",
      "repo": "https://github.com/community-user/docsight-pingtest",
      "version": "0.2.0",
      "minAppVersion": "2026.2",
      "type": "integration",
      "verified": false
    }
  ]
}
```

### Submission Process
1. Developer builds module in their own repo
2. Opens PR on `docsight-modules` adding entry to `registry.json`
3. Review: valid manifest? No malicious code? Works correctly?
4. Merge → module appears in catalog

### Verified Badge
Modules reviewed by the DOCSight team get `verified: true`. Unverified modules work but are marked accordingly in the UI.

## Security

### Technical Measures
- Manifest validation on load (schema, required fields, ID format)
- Route prefix enforced: module routes mount under `/api/modules/<id>/` — cannot override core routes
- Static files isolated under `/modules/<id>/static/`
- Broken modules are skipped, never crash the core

### Organizational Measures
- `verified` badge in catalog for reviewed modules
- Unverified warning in Settings UI
- README notice: "Community modules run with full container permissions. Only install modules you trust."
- TEMPLATE includes security guidelines for module authors

### What we intentionally skip
- No sandboxing (Docker container is the sandbox)
- No code signing (too complex for community project)
- No runtime permission prompts

Same approach as Home Assistant, Obsidian, and Discourse — the container itself is the trust boundary.

## Research Sources

Design informed by analysis of 7 plugin systems:
- Home Assistant Custom Components + HACS
- Grafana Plugins
- Obsidian Community Plugins
- VS Code Extensions
- WordPress Plugins
- Jellyfin Plugins
- Discourse Plugins
