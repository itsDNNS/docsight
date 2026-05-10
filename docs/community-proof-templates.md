# DOCSight community proof templates

Use these templates in GitHub Discussions when asking users to share real-world setups, evidence workflows, or modem compatibility reports. They are written to keep useful detail while reducing the chance that someone posts private data.

Live threads using these templates:

- [Share your DOCSight setup and what it helped you prove](https://github.com/itsDNNS/docsight/discussions/343)
- [Supported modem reports](https://github.com/itsDNNS/docsight/discussions/454)
- [ISP evidence outcomes](https://github.com/itsDNNS/docsight/discussions/455)

## Setup and evidence story

```md
## What were you trying to prove?

Briefly describe the problem:

- dropouts, slowdowns, latency, packet loss, upload issues, gaming, video calls, or something else
- how often it happened
- whether it was intermittent or constant

## Setup

- Country or region:
- Connection type:
- ISP, optional:
- Modem or router model:
- DOCSight deployment: Docker, Compose, systemd, NAS, other
- Integrations used: Speedtest, BQM, Smokeping, Home Assistant, MQTT, BNetzA, other

## What did DOCSight show?

- signal values or health states that changed
- event log entries
- speed, latency, or packet loss changes
- journal notes or attachments used
- before/after comparison, if any

## What helped most?

- dashboard
- signal trends
- correlation view
- event log
- incident journal
- complaint report
- before/after comparison
- another view or export

## What happened next?

- technician visit
- modem swap
- provider escalation
- local wiring change
- still investigating

## Safe screenshots or exports

Attach screenshots or report snippets only after removing:

- names, addresses, customer numbers, ticket numbers
- IP addresses, MAC addresses, serial numbers, hostnames
- exact location, Wi-Fi names, browser profile details
```

## Modem compatibility report

```md
## Modem or router

- Brand and model:
- Hardware revision, if visible:
- Firmware version, if visible:
- Country or region:
- ISP, optional:
- Bridge mode, router mode, or unknown:

## DOCSight setup

- DOCSight version:
- Deployment method: Docker, Compose, systemd, NAS, other
- Selected driver or mode:
- Authentication required: yes/no

## What works?

- downstream channels
- upstream channels
- SNR/MER
- power levels
- modulation
- correctable and uncorrectable errors
- event log
- speed or latency integrations

## What is missing or wrong?

- unsupported counters
- values shown as N/A
- parsing errors
- login problems
- layout changes in modem UI

## Safe evidence

Attach redacted screenshots or short text excerpts only if they do not contain credentials, cookies, session tokens, IP addresses, MAC addresses, serial numbers, or customer data.

Do not post raw HAR captures publicly. They often contain cookies, tokens, URLs, headers, and device identifiers that are hard to fully sanitize.
```

## ISP evidence outcome

```md
## Starting point

- What did the ISP say?
- What problem were you experiencing?
- How long did you collect data before acting?

## Evidence package

- DOCSight views used:
- Report or export used:
- BNetzA or other official measurement included, if any:
- Before/after comparison included: yes/no

## Outcome

- Ticket accepted
- Technician scheduled
- Modem replaced
- Line or house wiring fixed
- ISP still investigating
- No change yet

## What would help the next user?

Share the one thing you wish you had known before collecting evidence.

## Privacy reminder

Please remove names, addresses, contract numbers, ticket numbers, IPs, MACs, serials, and screenshots of private ISP portals before posting.
```
