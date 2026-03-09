# Repository Guidelines

## Project Structure & Module Organization
DOCSight is a Flask-based cable diagnostics app. Core application code lives in `app/`, with modem drivers in `app/drivers/`, data collectors in `app/collectors/`, built-in modules in `app/modules/`, blueprints in `app/blueprints/`, Jinja templates in `app/templates/`, and translations in `app/i18n/`. Tests live in `tests/`. Docker files (`Dockerfile`, `docker-compose.yml`, `docker-compose.dev.yml`) and contributor docs (`README.md`, `CONTRIBUTING.md`, `ARCHITECTURE.md`) are kept at the repo root. Assets and screenshots are under `docs/`.

## Build, Test, and Development Commands
- `pip install -r requirements.txt` installs runtime dependencies.
- `python -m app.main` starts the app locally on port `8765`.
- `SECRET_KEY=test python -m pytest tests/ -q --ignore=tests/e2e` runs the standard test suite.
- `docker compose -f docker-compose.dev.yml up -d --build` starts the demo-oriented dev stack on `http://localhost:8767`.
- `docker compose up -d` runs the production-style local stack on `8765`.

## Coding Style & Naming Conventions
Use 4-space indentation and keep changes minimal. Follow the existing Flask/pytest style in nearby files. New modem integrations should implement `ModemDriver`; new data sources should implement `Collector`. Prefer descriptive snake_case for Python names and keep route, module, and template names consistent (`*_bp.py`, `*_settings.html`, etc.). Update all four i18n files (`en`, `de`, `fr`, `es`) when UI strings change.

## Testing Guidelines
Use `pytest`. Add or extend targeted tests for every behavior change, especially for drivers, collectors, analyzers, API routes, and i18n-sensitive UI output. Name tests after the unit under test, for example `tests/test_surfboard_driver.py`. Run the full suite before opening a PR.

## Commit & Pull Request Guidelines
Recent history uses short imperative subjects such as `fix: surfboard session lifecycle...` and `chore: clarify modem support request template`. Keep commits focused and scoped. Open an issue before starting any non-trivial feature or architectural change. PRs should explain the change, link the related issue, note test coverage, and include screenshots for UI changes. Do not bundle unrelated work.

## Security & Contributor Notes
Never commit secrets, local config, planning files, or machine-specific notes. Keep `CLAUDE.md`, `.planning/`, `.codex/`, AGENT MEMORY exports, and similar private workflow files out of the repo. For modem support work, prefer the issue template and wiki flow instead of ad hoc captures.

