<p align="center">
  <img src="docs/docsight-logo-v2.svg" alt="DOCSight" width="128">
</p>

<h1 align="center">DOCSight</h1>

<p align="center">
  <a href="https://itsdnns.github.io/docsight/">Product page</a>&nbsp;&nbsp;&bull;&nbsp;&nbsp;
  <a href="#get-started">Get Started</a>&nbsp;&nbsp;&bull;&nbsp;&nbsp;
  <a href="https://github.com/itsDNNS/docsight/releases/latest">Windows Preview</a>&nbsp;&nbsp;&bull;&nbsp;&nbsp;
  <a href="#supported-hardware">Supported Hardware</a>&nbsp;&nbsp;&bull;&nbsp;&nbsp;
  <a href="https://github.com/itsDNNS/docsight/wiki">Wiki</a>&nbsp;&nbsp;&bull;&nbsp;&nbsp;
  <a href="DATA_CONTRACT.md">Data contract</a>&nbsp;&nbsp;&bull;&nbsp;&nbsp;
  <a href="CODE_SIGNING.md">Code signing</a>&nbsp;&nbsp;&bull;&nbsp;&nbsp;
  <a href="https://github.com/itsDNNS/docsight/releases">Releases</a>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/github/license/itsDNNS/docsight" alt="License"></a>
  <a href="https://github.com/itsDNNS/docsight/pkgs/container/docsight"><img src="https://img.shields.io/github/v/tag/itsDNNS/docsight?label=version" alt="Version"></a>
  <a href="https://github.com/itsDNNS/docsight/stargazers"><img src="https://img.shields.io/github/stars/itsDNNS/docsight?style=flat" alt="Stars"></a>
  <a href="https://github.com/itsDNNS/docsight/pkgs/container/docsight"><img src="https://ghcr-badge.egpl.dev/itsdnns/docsight/size" alt="Image Size"></a>
  <a href="https://selfh.st/weekly/2026-02-27/"><img src="https://img.shields.io/badge/selfh.st-Featured-blue" alt="Featured in selfh.st Weekly"></a>
</p>

<p align="center">
  <strong>Local monitoring and diagnostic reports for your internet connection.</strong>
</p>

<p align="center">
  Keep DOCSIS signal history, speed tests, latency, events, and incident notes together to investigate intermittent problems and share reports with your ISP.
</p>

<p align="center">
  <strong>Self-hosted</strong> • <strong>Local data</strong> • <strong>MIT</strong>
</p>

<p align="center">
  <img src="docs/screenshots/dashboard-hero.png" alt="DOCSight product dashboard with signal health, speed, latency and connection cards" width="100%" />
</p>

<p align="center">
  <em>Synthetic demo data in the real product UI: signal health, speed, latency, and connection context in one dashboard.</em>
</p>

---

## Get Started

The commands below require a running Docker engine. For Windows setup, see the [Windows quick start](docs/windows-quick-start.md). To try DOCSight without Docker, use the unsigned portable [Windows Desktop Preview](docs/windows-desktop-preview.md); for a native Python installation, see [INSTALL.md](INSTALL.md#bare-metal--systemd).

### Option 1: Try the demo

No router required. Demo mode generates synthetic DOCSIS history so you can explore the app.

```bash
docker run -d --name docsight-demo -p 8765:8765 -e DEMO_MODE=true ghcr.io/itsdnns/docsight:latest
```

### Option 2: Connect your own modem or router

```bash
docker run -d --name docsight --restart unless-stopped -p 8765:8765 -v docsight_data:/data ghcr.io/itsdnns/docsight:latest
```

Open `http://localhost:8765`. For your own connection, follow the setup wizard to select a [supported modem or Generic Router](#supported-hardware). Configuration and history are stored in the `docsight_data` volume.

[Windows quick start](docs/windows-quick-start.md) | [Full installation guide](https://github.com/itsDNNS/docsight/wiki/Installation) | [Example Compose Stacks](https://github.com/itsDNNS/docsight/wiki/Example-Compose-Stacks)

---

## Evidence journey

A few key views from the workflow:

| See what is happening now | Find the pattern |
|---|---|
| ![DOCSight dashboard with current signal health, speed, and active issue cards](docs/screenshots/dashboard-dark.png) | ![DOCSight signal trends showing long-term signal patterns](docs/screenshots/trends.png) |
| Current signal health, speed, latency, and active issues sit in one view. | Review signal changes over time. |

| Connect the signals | Bring something useful to support |
|---|---|
| ![DOCSight correlation view lining up signal, speed, and event history](docs/screenshots/correlation.png) | ![DOCSight evidence package workflow for local report generation](docs/screenshots/complaint-workflow.png) |
| Signal drops, packet loss, speed dips, modem events, and notes line up in one timeline. | Export a report for a selected incident or time window. |

---

## Public proof pack

See the [sample complaint report PDF](docs/samples/demo-complaint-report.pdf) and [proof-pack notes](docs/proof-pack.md) for an example using synthetic data. Complaint templates and BNetzA workflows focus on Germany; reports do not guarantee an ISP or legal outcome.

---

## Your Data Stays With You

Monitoring history and generated reports stay on your own hardware. Optional integrations communicate with the services you configure. Review exports before sharing: they can contain connection details and incident notes.

See the [Data contract](DATA_CONTRACT.md) for storage and sharing boundaries, and the [Security policy](SECURITY.md) for supported versions and vulnerability reporting.

---

## Features

### Core Evidence Workflow

| Feature | Why it matters |
|---|---|
| **[Live Dashboard](https://github.com/itsDNNS/docsight/wiki/Features-Dashboard)** | See current signal health, active issues, and actionable diagnostics at a glance |
| **[Signal Trends](https://github.com/itsDNNS/docsight/wiki/Features-Signal-Trends)** | Turn intermittent instability into visible long-term patterns |
| **[Connection Monitor](https://github.com/itsDNNS/docsight/wiki/Features-Connection-Monitor)** | Track latency, packet loss, outages, traceroute evidence, and raw ping logs continuously |
| **[Event Log](https://github.com/itsDNNS/docsight/wiki/Features-Event-Log)** | Automatically record anomalies like modulation drops and modem restarts |
| **[Incident Journal](https://github.com/itsDNNS/docsight/wiki/Features-Incident-Journal)** | Add notes, attachments, reviewed imports, and incident groupings |
| **Evidence Journey** | Review an incident or custom time window, see ready/stale/missing evidence, and carry that exact fixed period into complaint and PDF generation |
| **[DE · TKG compensation](https://github.com/itsDNNS/docsight/wiki/Features-TKG-Compensation)** | Check possible compensation for a complete outage or missed provider appointment, calculate a possible amount, and prepare an editable provider letter locally |
| **[Before/After Comparison](https://github.com/itsDNNS/docsight/wiki/Features-Before-After-Comparison)** | Compare measurements before and after a technician visit or ISP change |
| **[Correlation Analysis](https://github.com/itsDNNS/docsight/wiki/Features-Correlation-Analysis)** | Combine signal, speed, and event history in one timeline |
| **[Complaint Generator](https://github.com/itsDNNS/docsight/wiki/Filing-a-Complaint)** | Build ISP-ready evidence packages with letter text, checklist, and PDF output |

### Analysis, Integrations, and Power Features

| Category | Includes |
|---|---|
| **Network analysis** | [Gaming Quality Index](https://github.com/itsDNNS/docsight/wiki/Features-Gaming-Quality), [Modulation Performance](https://github.com/itsDNNS/docsight/wiki/Features-Modulation-Performance), [Channel Timeline](https://github.com/itsDNNS/docsight/wiki/Features-Channel-Timeline), [Cable Segment Utilization](https://github.com/itsDNNS/docsight/wiki/Features-Segment-Utilization) |
| **External data sources** | Guided setup for [Speedtest Integration](https://github.com/itsDNNS/docsight/wiki/Features-Speedtest), [BQM Integration](https://github.com/itsDNNS/docsight/wiki/Features-BQM), and [Smokeping Integration](https://github.com/itsDNNS/docsight/wiki/Features-Smokeping), plus [Smart Capture](https://github.com/itsDNNS/docsight/wiki/Features-Smart-Capture) and [BNetzA Measurements](https://github.com/itsDNNS/docsight/wiki/Features-BNetzA) |
| **Platform features** | [Home Assistant](https://github.com/itsDNNS/docsight/wiki/Home-Assistant), [Notifications](https://github.com/itsDNNS/docsight/wiki/Notifications), [Backup & Restore](https://github.com/itsDNNS/docsight/wiki/Backup-and-Restore), setup wizard, optional authentication, API tokens |
| **Usability and extensibility** | [Demo Mode](https://github.com/itsDNNS/docsight/wiki/Features-Demo-Mode), [Theme Engine](https://github.com/itsDNNS/docsight/wiki/Themes), [Community Modules](https://github.com/itsDNNS/docsight-modules), [In-App Glossary](https://github.com/itsDNNS/docsight/wiki/Features-Glossary), [AI/LLM Export](https://github.com/itsDNNS/docsight/wiki/Features-LLM-Export) with local redaction controls |

The core interface supports 24 languages, light/dark themes, and PWA/offline use.

---

## Extended screenshot gallery

<details>
<summary>See the extended screenshot gallery</summary>

| Dashboard (Light) | Health Assessment |
|---|---|
| ![Light](docs/screenshots/dashboard-light.png) | ![Health](docs/screenshots/health-banner.png) |

| Speedtest Tracker | Import (Excel/CSV) |
|---|---|
| ![Speedtest](docs/screenshots/speedtest.png) | ![Import](docs/screenshots/import-modal.png) |

| Edit with Icon Picker | Channel Timeline |
|---|---|
| ![Edit](docs/screenshots/incident-edit.png) | ![Channel Timeline](docs/screenshots/channel-timeline.png) |

| Event Log | Settings |
|---|---|
| ![Events](docs/screenshots/events.png) | ![Settings](docs/screenshots/settings.png) |

| Theme Gallery | BQM Integration |
|---|---|
| ![Themes](docs/screenshots/themes.png) | ![BQM](docs/screenshots/bqm.png) |

</details>

---

## Supported Hardware

DOCSight supports **21 modem families** out of the box. DOCSIS signal monitoring requires a supported cable modem. **Generic Router mode** supports other connections, including fiber, DSL, and satellite, with speed tests, latency monitoring, notes, and reports but no DOCSIS signal data.

Signal health and SC-QAM capacity estimates describe the physical/channel layer; they are not measurements of internet throughput or tariff speed.

### Common setups

- **CGA4233 / TG3442DE cable gateways:** bridge mode compatible
- **AVM FRITZ!Box Cable** (6490, 6590, 6591, 6660, 6690)
- **Sercomm Ultra Hub 7 class gateways**
- **CH7465 Connect Box family**
- **Sagemcom F@st 3896:** JSON-RPC API
- **Sagemcom F3896LG** (Hub 5 / Liberty Global REST firmware): unauthenticated API, works in modem mode
- **Technicolor TC4400**
- **Arris SURFboard** (S33, S34, SB8200): HNAP1 API
- **Arris SURFboard SB8200** (CBN firmware, `SB8200v3`): XML API, for units that serve the CBN web UI instead of HNAP1
- **Arris SB6183:** HTTP status pages, no authentication required
- **Hitron CODA-56 and CODA-4680**
- **Netgear CM3000**
- **Netgear CM1000**

[See the full compatibility and setup docs in the wiki →](https://github.com/itsDNNS/docsight/wiki)

Community drivers and extensions live in [docsight-modules](https://github.com/itsDNNS/docsight-modules), and you can also [add your own modem support](https://github.com/itsDNNS/docsight/wiki/Adding-Modem-Support).

---

## Community and Support

For setup help, use [GitHub Discussions](https://github.com/itsDNNS/docsight/discussions/categories/q-a). See [SUPPORT.md](SUPPORT.md) for troubleshooting steps, the local doctor command, and where to report bugs or request modem support. Report vulnerabilities through the [Security policy](SECURITY.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). **Please open an issue or start an Ideas discussion before working on new features.**

## Support

You can support development through:

<a href="https://github.com/sponsors/itsDNNS"><img src="https://img.shields.io/badge/GitHub%20Sponsors-Support%20DOCSight-24292f?logo=github&logoColor=white" alt="GitHub Sponsors"></a>
<a href="https://ko-fi.com/itsdnns"><img src="https://img.shields.io/badge/Ko--fi-Support%20DOCSight-ff5e5b?logo=ko-fi&logoColor=white" alt="Ko-fi"></a>
<a href="https://paypal.me/itsDNNS"><img src="https://img.shields.io/badge/Donate-PayPal-00457C?logo=paypal&logoColor=white" alt="PayPal"></a>

## Brand Use

The code is MIT-licensed, but the `DOCSight` name, logo, and project branding are governed separately. Community forks and commercial services may say they are "based on DOCSight" or "compatible with DOCSight", but must not present themselves as the official project without permission.

See [TRADEMARKS.md](TRADEMARKS.md) for the full brand and trademark policy.

## Documentation

| Document | Scope |
|---|---|
| [Wiki](https://github.com/itsDNNS/docsight/wiki) | User guides, feature docs, setup instructions |
| [Data contract](DATA_CONTRACT.md) | Local storage, integrations, and export boundaries |
| [Apprise notification sidecar](docs/notifications-apprise.md) | Optional alert fan-out through an Apprise API sidecar |
| [PWA Web Push notifications](docs/notifications-pwa-web-push.md) | Optional browser/app push alerts through the installed PWA |
| [Community proof templates](docs/community-proof-templates.md) | Public-safe templates for setup stories, modem reports, and ISP evidence outcomes |
| [Installation](INSTALL.md) | Docker, native Python, and reverse-proxy setup |
| [GitHub Releases](https://github.com/itsDNNS/docsight/releases) | Versioned builds and release notes |
| [SUPPORT.md](SUPPORT.md) | Support routing, community channels, and issue guidance |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Technical architecture and extension guide |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Development and contribution guidelines |
| [TRADEMARKS.md](TRADEMARKS.md) | Brand, logo, and official-use policy |

## License

[MIT](LICENSE)

<p align="center">
  <sub><strong>DOCSight</strong> = <strong>DOCS</strong>IS + In<strong>sight</strong> (+ a quiet <em>sigh</em> from every cable internet user)</sub>
</p>
