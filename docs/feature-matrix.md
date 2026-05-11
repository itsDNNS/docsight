# DOCSight feature matrix

This page keeps public positioning honest by separating shipped capabilities from planned or intentionally out-of-scope work.

## Shipped today

| Area | Status | Notes |
|---|---|---|
| DOCSIS signal monitoring | Shipped | Signal health, channels, modulation, SNR and power history for supported modem families. |
| Generic Router mode | Shipped | Useful for non-cable connections, but strongest DOCSIS evidence needs cable signal data. |
| Demo mode | Shipped | Generates realistic synthetic history for evaluation without a modem. |
| Correlation analysis | Shipped | Combines signal, speed, latency, events and notes into one investigation view. |
| Incident journal | Shipped | Notes, imports, reviewed events and incident groupings. |
| Complaint workflow | Shipped | Report generation, complaint-ready text and a sample public proof report. |
| Before/after comparison | Shipped | Helps compare a fix window, technician visit or provider change. |
| Speedtest, BQM and Smokeping inputs | Shipped | Optional external data sources for the evidence timeline. |
| Home Assistant and MQTT | Shipped | Local automation and monitoring integrations. |
| PWA and offline shell | Shipped | Installable app shell with local-first operation semantics. |
| Community modules | Shipped | Extension path for modem support and optional features. |

## Planned or under evaluation

| Area | Status | Notes |
|---|---|---|
| More modem drivers | Ongoing | Community reports and drivers expand compatibility over time. |
| More sample reports | Planned | Additional synthetic examples for before/after and non-Germany workflows. |
| Community evidence stories | Ongoing | Public examples require explicit permission and careful redaction. |
| Comparison page | Planned | A deeper public guide comparing DOCSight with uptime, speedtest and latency tools. |

## Intentionally out of scope

| Area | Reason |
|---|---|
| Legal guarantee | DOCSight documents evidence but cannot guarantee ISP or regulator outcomes. |
| Managed cloud monitoring | The project is local-first and self-hosted. |
| Public status-page replacement | DOCSight can help diagnose connection history, but uptime status pages are a different product class. |
| Universal fault detection | Results depend on modem support, configured inputs and the data available from the local setup. |
