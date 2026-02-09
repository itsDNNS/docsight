# DOCSight

Docker container that monitors DOCSIS channel health on cable modems and publishes per-channel sensor data to Home Assistant via MQTT Auto-Discovery. Currently supports AVM FRITZ!Box Cable routers.

## Features

- **Per-Channel Sensors**: Every downstream/upstream DOCSIS channel becomes its own Home Assistant sensor with full attributes (frequency, modulation, SNR, errors, DOCSIS version)
- **Summary Sensors**: Aggregated metrics (power min/max/avg, SNR, error counts, overall health)
- **Health Assessment**: Automatic traffic-light evaluation based on industry-standard thresholds
- **Web UI**: Built-in dashboard on port 8765 with timeline navigation and light/dark mode
- **Setup Wizard**: Browser-based configuration - no .env file needed
- **Settings Page**: Change all settings at runtime, test connections, toggle themes
- **Internationalization**: English and German UI
- **LLM Export**: Generate structured reports for AI analysis
- **MQTT Auto-Discovery**: Zero-config integration with Home Assistant

## Quick Start

```bash
git clone https://github.com/itsDNNS/docsight.git
cd docsight
docker compose up -d
```

Open `http://localhost:8765` - the setup wizard guides you through configuration.

## Configuration

Configuration is stored in `config.json` inside the Docker volume and persists across restarts. You can also use environment variables (they override config.json values).

### Via Web UI (recommended)

1. Start the container - the setup wizard opens automatically
2. Enter FritzBox URL, username, and password - test the connection
3. Optionally enter MQTT broker details - test the connection
4. Set poll interval and history retention
5. Done - monitoring starts immediately

Access `/settings` at any time to change configuration or toggle light/dark mode.

### Via Environment Variables (optional)

Copy `.env.example` to `.env` and edit:

| Variable | Default | Description |
|---|---|---|
| `FRITZ_URL` | `http://192.168.178.1` | FritzBox URL |
| `FRITZ_USER` | - | FritzBox username |
| `FRITZ_PASSWORD` | - | FritzBox password |
| `MQTT_HOST` | `localhost` | MQTT broker host |
| `MQTT_PORT` | `1883` | MQTT broker port |
| `MQTT_USER` | - | MQTT username (optional) |
| `MQTT_PASSWORD` | - | MQTT password (optional) |
| `MQTT_TOPIC_PREFIX` | `docsight` | MQTT topic prefix |
| `POLL_INTERVAL` | `300` | Polling interval in seconds |
| `WEB_PORT` | `8765` | Web UI port |
| `HISTORY_DAYS` | `7` | Snapshot retention in days |

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

| Metric | Good | Marginal | Bad |
|---|---|---|---|
| DS Power | -7..+7 dBmV | +/-7..+/-10 | > +/-10 dBmV |
| US Power | 35..49 dBmV | 50..54 | > 54 dBmV |
| SNR / MER | > 30 dB | 25..30 | < 25 dB |

## Web UI

Access at `http://<host>:8765`. Auto-refreshes every 60 seconds. Shows:
- Health status with actionable recommendations
- Summary metrics and tariff info
- Full downstream/upstream channel tables with per-row health indicators
- Trend charts (day/week/month)
- Calendar navigation for historical snapshots
- LLM export for AI-powered analysis

## Requirements

- AVM FRITZ!Box Cable router (tested with 6690 Cable)
- MQTT broker (e.g., Mosquitto) - optional, for Home Assistant integration

## License

MIT
