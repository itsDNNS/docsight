# DOCSIS case fixtures

This directory contains public-safe DOCSIS evidence fixtures used by `tests/test_docsis_case_fixtures.py`.

Fixtures are synthetic and must not contain private IP addresses, MAC addresses, serial numbers, provider account data, cookies, tokens, passwords, or location-specific hints.

Run the focused replay suite with:

```bash
uv run pytest tests/test_docsis_case_fixtures.py
```

Each JSON case may define:

- `raw`: redacted raw DOCSIS input accepted by `app.analyzer.analyze()`.
- `previous_raw`: optional prior raw input for event/baseline replay.
- `postprocess`: optional collector-side post-processing to apply before assertions.
- `checklist`: optional evidence-checklist input for non-DOCSIS capability cases.
- `expect`: golden analyzer, event, or checklist expectations.
