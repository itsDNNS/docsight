# PWA Web Push notifications

DOCSight can send alerts to browsers that subscribe through the installed PWA or Settings page. This is a local delivery channel in the same notification pipeline as direct webhooks and Apprise: DOCSight still applies severity filtering, per-event toggles, cooldowns, and test notifications before any push message is sent.

PWA Web Push does not replace Apprise. Apprise is best when you want provider fan-out through Telegram, Matrix, ntfy, Gotify, email, or similar services. PWA Web Push is for browser and app notifications on devices that have granted permission to this DOCSight instance.

## Requirements

- DOCSight must be served over HTTPS, or over `localhost` during local testing. Browsers require a secure context for Push API subscriptions.
- A service worker must be registered by the browser. DOCSight's bundled service worker handles offline caching and push events.
- You need a VAPID key pair for this DOCSight instance.
- Each browser/device must subscribe explicitly from Settings. DOCSight does not request notification permission on page load.

## Configuration

Open Settings → Notifications and configure:

- Enable PWA Web Push: on
- VAPID Public Key: the browser-facing public key
- VAPID Private Key: the server-side private key, stored encrypted at rest
- VAPID Subject: a contact URI for push services, for example `mailto:admin@example.com`

After saving the VAPID settings, use **Subscribe this browser** on each browser/device that should receive alerts. Use **Unsubscribe this browser** to remove the current browser subscription.

You can also configure the same values through environment variables:

- `NOTIFY_PWA_PUSH_ENABLED=true`
- `NOTIFY_PWA_PUSH_VAPID_PUBLIC_KEY=...`
- `NOTIFY_PWA_PUSH_VAPID_PRIVATE_KEY=...`
- `NOTIFY_PWA_PUSH_VAPID_SUBJECT=mailto:admin@example.com`

Do not share or publish the private key.

## Delivery behavior

- Existing severity filters, per-event disables, and cooldowns are applied before PWA Web Push delivery.
- The test notification route sends to all configured channels, including subscribed browsers when PWA Web Push is configured.
- Push payloads are intentionally short and do not include raw event details. They include title, body, severity, event type, timestamp, and a local URL.
- Expired browser subscriptions are removed when the push service returns a permanent gone/not-found response.

## Privacy and security

Browser push providers may see delivery metadata according to the browser/vendor push service in use. DOCSight keeps event selection local and sends only a minimal notification payload. The VAPID private key is a DOCSight secret, is masked in Settings, and is encrypted at rest in `data/config.json`.

## Troubleshooting

- If the browser says Web Push is unsupported, check that you are using a browser with Push API support and that DOCSight is served from HTTPS or localhost.
- If the status says Web Push is not configured, save the enable toggle and both VAPID keys first.
- If permission was denied, change the browser/site notification permission manually and try subscribing again.
- If a device stops receiving alerts, unsubscribe and subscribe that browser again to refresh its endpoint.
