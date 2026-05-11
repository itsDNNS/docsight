# DOCSight public surface follow-up issues

These are intentionally narrow follow-ups discovered while preparing the public landing page.

## 1. Add a report-preview screenshot to the proof pack

Goal: show the first page of the synthetic complaint report as a browser or in-app preview.

Acceptance criteria:

- Uses `Example Cable Provider` and `Demo DOCSIS Gateway`.
- Contains no real provider, customer, address, IP, MAC, serial number or ticket data.
- Is visually checked at README scale.
- Is referenced from `docs/proof-pack.md` only after passing the public screenshot checklist.

## 2. Create a deeper comparison page

Goal: explain when to use DOCSight alongside uptime monitors, speedtest trackers, SmokePing/BQM, Prometheus/Grafana and raw DOCSIS scrapers.

Acceptance criteria:

- Category-level comparison only, no hostile product takedowns.
- Clear note that DOCSight documents evidence but does not guarantee outcomes.
- Links back to the demo, proof pack and installation docs.

## 3. Collect redacted community evidence stories

Goal: invite users to share what DOCSight helped them diagnose without exposing private connection data.

Acceptance criteria:

- Discussion prompt asks for redacted screenshots or short excerpts, not raw HAR files.
- Template asks for modem family, region, symptom, evidence used and outcome.
- Privacy warning is visible before users post.
