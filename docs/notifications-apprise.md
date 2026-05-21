# Apprise notification sidecar

DOCSight can send alerts to an optional [Apprise API](https://github.com/caronc/apprise-api) sidecar. DOCSight still decides *when* to notify: severity filtering, per-event toggles, cooldowns, test notifications, and event context all stay in DOCSight. Apprise decides *where* to deliver the alert, for example Telegram, Matrix, ntfy, Gotify, Slack, Pushover, email, or another Apprise-supported target.

Apprise is optional. The existing direct webhook and Discord webhook paths remain available for simple setups.

## Docker Compose example

```yaml
services:
  docsight:
    image: ghcr.io/itsdnns/docsight:latest
    container_name: docsight
    restart: unless-stopped
    ports:
      - "8765:8765"
    volumes:
      - docsight_data:/data
    cap_add:
      - NET_RAW

  apprise:
    image: caronc/apprise:latest
    container_name: docsight-apprise
    restart: unless-stopped
    ports:
      - "8000:8000"
    volumes:
      - apprise_config:/config

volumes:
  docsight_data:
  apprise_config:
```

Open the Apprise API UI at `http://HOST:8000`, create a persistent configuration, and add one or more notification targets. Then open DOCSight Settings → Notifications and configure:

- Enable Apprise: on
- Apprise API URL: `http://apprise:8000` when both services share the Compose network, or `http://HOST:8000` from another host
- Config key: the Apprise persistent configuration key, if you created one
- API token: optional Bearer token if your Apprise API deployment requires one
- Tags: optional comma-separated Apprise tags for route selection

If the config key is empty, DOCSight posts to Apprise's stateless `/notify` endpoint. That mode only works when your Apprise API server has stateless target URLs configured, for example through Apprise's `APPRISE_STATELESS_URLS` environment/config option. With a config key, DOCSight posts to `/notify/{config_key}` and Apprise uses the persistent configuration stored under that key.

## Target examples

Provider credentials and provider-specific routing belong in Apprise, not in DOCSight where possible. Examples of Apprise target URLs you can manage in Apprise:

- Telegram: `tgram://BOT_TOKEN/CHAT_ID`
- Matrix: `matrixs://USER:PASSWORD@matrix.example.org/!room:example.org`
- ntfy: `ntfy://ntfy.sh/docsight-alerts`
- Gotify: `gotify://gotify.example.org/TOKEN`
- Email: `mailtos://USER:PASSWORD@smtp.example.org?to=admin@example.org`

Check Apprise's upstream documentation for exact URL syntax and provider requirements.

## Responsibilities and privacy

- DOCSight sends only the notification payload it already builds for alert delivery: source, timestamp, severity, event type, message, and event details.
- DOCSight applies severity filters, per-event toggles, and cooldowns before Apprise delivery.
- Apprise may forward notification data to whatever providers you configure there. Review each provider's privacy expectations before adding it.
- Apprise URL, config key, API token, and tags are treated as sensitive or secret-adjacent in DOCSight settings. Secret fields are masked in the UI and encrypted at rest where applicable.
- Failed Apprise delivery logs identify the Apprise channel and HTTP status without logging the full URL, config key, or token.

## Not Home Assistant or PWA push

Apprise delivery is only an alert target. It does not replace DOCSight's MQTT Auto-Discovery/Home Assistant telemetry integration. Keep using MQTT Auto-Discovery for sensors and Home Assistant dashboards.

Apprise also does not replace PWA/Web Push. Browser push still needs service worker handling, browser permissions, subscriptions, and click/deep-link behavior.
