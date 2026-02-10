<p align="center">
  <img src="docs/docsight.png" alt="DOCSight" width="128">
</p>

<h1 align="center">DOCSight</h1>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/github/license/itsDNNS/docsight" alt="License"></a>
  <a href="https://github.com/itsDNNS/docsight/pkgs/container/docsight"><img src="https://img.shields.io/github/v/tag/itsDNNS/docsight?label=version" alt="Version"></a>
  <a href="https://github.com/itsDNNS/docsight"><img src="https://img.shields.io/github/last-commit/itsDNNS/docsight" alt="Last Commit"></a>
</p>

<p align="center">
  Self-hosted cable internet monitoring and diagnostics. Track DOCSIS signal levels, detect problems, and get actionable health assessments — right in your browser.
</p>

![Dashboard Dark Mode](docs/screenshots/dashboard-dark.png)

## Why DOCSight

Cable internet dropping out, buffering, or slower than it should be? Your ISP says "everything looks fine"? DOCSight reads the DOCSIS signal levels directly from your modem and tells you whether the problem is on your end or your provider's. It gives you real data — power levels, signal-to-noise ratios, error counts — that you can show a technician or use to hold your ISP accountable.

## Table of Contents

- [Why DOCSight](#why-docsight)
- [Features](#features)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Screenshots](#screenshots)
- [Home Assistant Integration](#home-assistant-integration)
- [Reference Values](#reference-values)
- [Requirements](#requirements)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [Changelog](#changelog)

## Features

**Monitoring & Diagnostics**
- **Web Dashboard**: Real-time channel data with health assessment, trend charts, and calendar navigation
- **Health Assessment**: Automatic traffic-light evaluation with actionable recommendations
- **Trend Charts**: Track signal quality over days, weeks, or months to spot recurring issues
- **LLM Export**: Generate structured reports for AI analysis (ChatGPT, Claude, Gemini, etc.)
- **ThinkBroadband BQM**: Daily fetch and archive of broadband quality graphs with gallery view

**Ease of Use**
- **Setup Wizard**: Browser-based configuration — no .env file needed
- **4 Languages**: English, German, French, and Spanish UI
- **Light/Dark Mode**: Persistent theme toggle
- **Optional Authentication**: Password-protected web UI with scrypt hashing

**Smart Home Integration** (optional)
- **MQTT Auto-Discovery**: Zero-config integration with Home Assistant
- **Per-Channel + Summary Sensors**: Every DOCSIS channel and aggregated metrics as HA entities

## Quick Start

```bash
docker run -d --name docsight -p 8765:8765 -v docsight_data:/data ghcr.io/itsdnns/docsight:latest
```

Open `http://localhost:8765` - the setup wizard guides you through configuration.

For Docker Compose, Portainer, Dockhand, and detailed step-by-step instructions, see the **[Installation Guide](INSTALL.md)**.

<details>
<summary><h2>Configuration</h2></summary>

Configuration is stored in `config.json` inside the Docker volume and persists across restarts. Environment variables override config.json values.

### Via Web UI (recommended)

1. Start the container - the setup wizard opens automatically
2. Enter your modem URL, username, and password - test the connection
3. Optionally configure MQTT broker for Home Assistant integration
4. Set poll interval, history retention, and language
5. Done - monitoring starts immediately

Access `/settings` at any time to change configuration, set an admin password, or toggle light/dark mode.

### Via Environment Variables (optional)

Copy `.env.example` to `.env` and edit:

| Variable | Default | Description |
|---|---|---|
| `MODEM_URL` | `http://192.168.178.1` | Modem URL |
| `MODEM_USER` | - | Modem username |
| `MODEM_PASSWORD` | - | Modem password |
| `MQTT_HOST` | - | MQTT broker host (optional) |
| `MQTT_PORT` | `1883` | MQTT broker port |
| `MQTT_USER` | - | MQTT username (optional) |
| `MQTT_PASSWORD` | - | MQTT password (optional) |
| `MQTT_TOPIC_PREFIX` | `docsight` | MQTT topic prefix |
| `POLL_INTERVAL` | `900` | Polling interval in seconds |
| `WEB_PORT` | `8765` | Web UI port |
| `HISTORY_DAYS` | `0` | Snapshot retention in days (0 = unlimited) |
| `ADMIN_PASSWORD` | - | Web UI password (optional) |
| `BQM_URL` | - | ThinkBroadband BQM share URL (.png, optional) |

</details>

<details>
<summary><h2>Screenshots</h2></summary>

| Dashboard (Dark) | Dashboard (Light) | Setup Wizard |
|---|---|---|
| ![Dark](docs/screenshots/dashboard-dark.png) | ![Light](docs/screenshots/dashboard-light.png) | ![Setup](docs/screenshots/setup.png) |

| Trend Charts | Health Banner |
|---|---|
| ![Trends](docs/screenshots/trends.png) | ![Health](docs/screenshots/health-banner.png) |

</details>

<details>
<summary><h2>Home Assistant Integration</h2></summary>

DOCSight can optionally publish all channel data to Home Assistant via MQTT Auto-Discovery. This is not required to use DOCSight.

### Per-Channel (~37 DS + 4 US)

- `sensor.docsight_ds_ch{id}` - State: Power (dBmV), Attributes: frequency, modulation, snr, errors, docsis_version, health
- `sensor.docsight_us_ch{id}` - State: Power (dBmV), Attributes: frequency, modulation, multiplex, docsis_version, health

### Summary (14)

| Sensor | Unit | Description |
|---|---|---|
| `docsight_health` | - | Overall health (good/marginal/poor) |
| `docsight_health_details` | - | Detail text |
| `docsight_ds_total` | - | Number of downstream channels |
| `docsight_ds_power_min/max/avg` | dBmV | Downstream power range |
| `docsight_ds_snr_min/avg` | dB | Downstream signal-to-noise |
| `docsight_ds_correctable_errors` | - | Total correctable errors |
| `docsight_ds_uncorrectable_errors` | - | Total uncorrectable errors |
| `docsight_us_total` | - | Number of upstream channels |
| `docsight_us_power_min/max/avg` | dBmV | Upstream power range |

</details>

<details>
<summary><h2>Reference Values</h2></summary>

| Metric | Good | Marginal | Poor |
|---|---|---|---|
| DS Power | -7..+7 dBmV | +/-7..+/-10 | > +/-10 dBmV |
| US Power | 35..49 dBmV | 50..54 | > 54 dBmV |
| SNR / MER | > 30 dB | 25..30 | < 25 dB |

</details>

## Requirements

- Docker (or any OCI-compatible container runtime)
- A DOCSIS cable modem or router with web interface (tested with AVM FRITZ!Box 6690 Cable)
- MQTT broker (optional) — only needed for Home Assistant integration

## Roadmap

### Modulation & Signal Intelligence
- [ ] **Modulation Watchdog**: Track and alert on QAM modulation changes per channel (e.g. 256QAM dropping to 16QAM) — the #1 symptom users report in cable forums
- [ ] **Channel Heatmap**: Visual grid of all channels color-coded by modulation quality — spot frequency-dependent issues at a glance
- [ ] **OFDMA Analysis**: Detect whether the modem uses a wide OFDMA block vs. many narrow SC-QAMs; flag subcarrier count fluctuations as potential ingress indicators; track OFDMA enable/disable impact
- [ ] **Adaptive Polling**: Automatically increase poll frequency (e.g. every 10-30s) when uncorrectable errors spike, to capture incidents in high resolution
- [ ] **Upstream Channel Count Monitoring**: Alert when upstream channels drop (e.g. from 5 to 1) — early indicator of return path issues
- [ ] **Ingress/Return Path Scoring**: Composite score based on upstream power levels, modulation quality, and channel count to detect return path interference before total failure

### Diagnosis & Reporting
- [ ] **Incident Report Export**: One-click PDF/report with worst modulation values, max power levels, error sums, and auto-generated ISP complaint text referencing DIN thresholds — ready to email to your ISP's tech support
- [ ] **Ping Correlation**: Built-in latency monitor (ping to configurable targets) overlaid on error graphs to prove causality between physical layer issues and packet loss — replaces manual PingPlotter usage
- [ ] **Before/After Comparison**: Side-by-side overlay of two time periods (e.g. week before vs. after technician visit) to quantify improvements
- [ ] **FritzBox Event Log Parser**: Extract and display T3/T4 Timeout events, Ranging Request failures, and other DOCSIS error codes from the modem's event log
- [ ] **Plain-Language Explanations**: "What does this mean?" tooltips translating technical values into actionable advice (e.g. "Your upstream power is critically high — this means the signal has to travel too far or passes through damaged cable")

### Alerting & Notifications
- [ ] **Notification System**: Configurable alerts via webhook, Telegram, Discord, email, or Gotify/ntfy on health degradation, modulation drops, or connectivity loss
- [ ] **Power Level Drift Detection**: Alert on relative changes (e.g. +3 dB in 24h) in addition to absolute thresholds — catch creeping degradation before it causes outages
- [ ] **Scheduled Health Digest**: Daily/weekly summary email or message with connection quality score, error trends, and notable events
- [ ] **Gaming/Real-Time Quality Index**: Dedicated score for latency-sensitive applications based on jitter, packet loss bursts, and modulation stability

### External Monitoring Integration
- [x] **ThinkBroadband BQM**: Daily fetch and archive of external broadband quality graphs (latency, packet loss)
- [ ] **Speedtest Tracker**: Pull speed test results (download, upload, ping, jitter) from self-hosted [Speedtest Tracker](https://github.com/alexjustesen/speedtest-tracker)
- [ ] **Smokeping Integration**: Import or display Smokeping latency data alongside DOCSIS metrics for end-to-end correlation

### Enhanced Dashboard
- [ ] Combined timeline: DOCSIS health + speed tests + BQM graph + ping data on a single time axis
- [ ] Mobile-responsive layout
- [ ] Segment load indicator: Visualize peak-hour degradation patterns (e.g. 20:00–23:00 slowdowns)
- [ ] Network uptime calendar: Month-view heatmap showing daily connection quality at a glance

### Multi-Modem Support
- [ ] Plugin architecture for modem drivers
- [ ] **Vodafone Station / CommScope driver**: Support for the most common ISP-provided cable modem in Germany
- [ ] **Arris / Technicolor / Sagemcom drivers**: Cover the long tail of ISP-provided hardware
- [ ] SNMP-based generic driver for additional cable modem models
- [ ] Community-contributed drivers with documentation template

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for a detailed list of changes per version.

## License

[MIT](LICENSE)
