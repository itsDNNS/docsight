<p align="center">
  <img src="docs/docsight.png" alt="DOCSight" width="128">
</p>

<h1 align="center">DOCSight</h1>

<p align="center">
  Docker container that monitors DOCSIS channel health on cable modems and publishes per-channel sensor data to Home Assistant via MQTT Auto-Discovery. Currently supports AVM FRITZ!Box Cable routers.
</p>

![Dashboard Dark Mode](docs/screenshots/dashboard-dark.png)

## Features

- **Web Dashboard**: Real-time channel data with health assessment, trend charts, and calendar navigation
- **Per-Channel Sensors**: Every downstream/upstream DOCSIS channel becomes its own Home Assistant sensor with full attributes
- **Summary Sensors**: Aggregated metrics (power min/max/avg, SNR, error counts, overall health)
- **Health Assessment**: Automatic traffic-light evaluation with actionable recommendations
- **Setup Wizard**: Browser-based configuration - no .env file needed
- **Settings Page**: Change all settings at runtime, test connections, toggle themes
- **Internationalization**: English and German UI
- **LLM Export**: Generate structured reports for AI analysis (ChatGPT, Claude, Gemini, etc.)
- **MQTT Auto-Discovery**: Zero-config integration with Home Assistant
- **Optional Authentication**: Password-protected web UI with scrypt hashing
- **Light/Dark Mode**: Persistent theme toggle

## Quick Start

```bash
docker run -d --name docsight -p 8765:8765 -v docsight_data:/data ghcr.io/itsdnns/docsight:latest
```

Open `http://localhost:8765` - the setup wizard guides you through configuration.

### Using Docker Compose

```bash
git clone https://github.com/itsDNNS/docsight.git
cd docsight
docker compose up -d
```

## Configuration

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
| `FRITZ_URL` | `http://192.168.178.1` | Modem URL |
| `FRITZ_USER` | - | Modem username |
| `FRITZ_PASSWORD` | - | Modem password |
| `MQTT_HOST` | - | MQTT broker host (optional) |
| `MQTT_PORT` | `1883` | MQTT broker port |
| `MQTT_USER` | - | MQTT username (optional) |
| `MQTT_PASSWORD` | - | MQTT password (optional) |
| `MQTT_TOPIC_PREFIX` | `docsight` | MQTT topic prefix |
| `POLL_INTERVAL` | `300` | Polling interval in seconds |
| `WEB_PORT` | `8765` | Web UI port |
| `HISTORY_DAYS` | `7` | Snapshot retention in days |
| `ADMIN_PASSWORD` | - | Web UI password (optional) |

## Screenshots

| Dashboard (Dark) | Dashboard (Light) | Setup Wizard |
|---|---|---|
| ![Dark](docs/screenshots/dashboard-dark.png) | ![Light](docs/screenshots/dashboard-light.png) | ![Setup](docs/screenshots/setup.png) |

| Trend Charts | Health Banner |
|---|---|
| ![Trends](docs/screenshots/trends.png) | ![Health](docs/screenshots/health-banner.png) |

## Created Sensors

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

## Reference Values

| Metric | Good | Marginal | Poor |
|---|---|---|---|
| DS Power | -7..+7 dBmV | +/-7..+/-10 | > +/-10 dBmV |
| US Power | 35..49 dBmV | 50..54 | > 54 dBmV |
| SNR / MER | > 30 dB | 25..30 | < 25 dB |

## Requirements

- AVM FRITZ!Box Cable router (tested with 6690 Cable)
- MQTT broker (e.g., Mosquitto) - optional, for Home Assistant integration

## Roadmap

### External Monitoring Integration
- [ ] **ThinkBroadband BQM**: Daily fetch and archive of external broadband quality graphs (latency, packet loss)
- [ ] **Speedtest Tracker**: Pull speed test results (download, upload, ping, jitter) from self-hosted [Speedtest Tracker](https://github.com/alexjustesen/speedtest-tracker)

### Enhanced Dashboard
- [ ] Combined timeline: DOCSIS health + speed tests + BQM graph on a single time axis
- [ ] Notification system: Webhooks on health degradation
- [ ] Mobile-responsive layout

### Multi-Modem Support
- [ ] Plugin architecture for modem drivers
- [ ] SNMP-based generic driver for non-FritzBox cable modems
- [ ] Community-contributed drivers (Arris, Technicolor, Sagemcom)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.

## License

[MIT](LICENSE)
