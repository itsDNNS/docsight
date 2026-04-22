# Support and Community Routing

DOCSight has a few different channels on purpose. Using the right one keeps troubleshooting faster, feature planning cleaner, and security issues private.

## Where to ask what

| Need | Best place | Why |
| --- | --- | --- |
| Setup help, troubleshooting, reverse proxy questions, Docker questions | [GitHub Discussions: Q&A](https://github.com/itsDNNS/docsight/discussions/categories/q-a) | Best for support threads that may help the next person too |
| Product ideas, feature suggestions, roadmap feedback | [GitHub Discussions: Ideas](https://github.com/itsDNNS/docsight/discussions/categories/ideas) | Good for shaping scope before work starts |
| Share your setup, dashboards, exports, or evidence workflow | [GitHub Discussions: Show and tell](https://github.com/itsDNNS/docsight/discussions/categories/show-and-tell) | Builds a public proof layer and gives others real-world examples |
| Confirmed bugs or regressions | [Bug report issue form](https://github.com/itsDNNS/docsight/issues/new?template=bug_report.yml) | Best when there is a reproducible problem to fix |
| Missing, outdated, or confusing docs | [Documentation improvement form](https://github.com/itsDNNS/docsight/issues/new?template=documentation.yml) | Best for README, wiki, setup, and screenshot fixes |
| Request support for a new modem model | [Modem support request form](https://github.com/itsDNNS/docsight/issues/new?template=modem_support.yml) | Collects the HAR file, screenshots, and firmware details needed for a driver |
| Security vulnerabilities | [Private security advisory](https://github.com/itsDNNS/docsight/security/advisories/new) | Keeps users safe and avoids publishing exploit details too early |
| Documentation, install, and architecture references | [Wiki](https://github.com/itsDNNS/docsight/wiki), [INSTALL.md](INSTALL.md), [ARCHITECTURE.md](ARCHITECTURE.md) | Start here before opening support threads |

## Before opening a bug

Please use a Q&A discussion first if you are still in the "not sure whether this is a bug or setup issue" stage.

When opening a bug, include:

- DOCSight version
- deployment method
- modem model or Generic Router mode
- steps to reproduce
- relevant logs or screenshots
- whether the issue also happens in demo mode, if applicable

## Before opening a documentation issue

Use the documentation form when the problem is missing guidance, stale screenshots, unclear wording, or a broken example in the README, wiki, installation docs, or architecture docs.

Useful details include:

- the page or file that needs work
- what is unclear, outdated, or missing
- what you expected to find
- screenshots or error output if a setup step failed

## Before requesting modem support

Please follow the [Requesting Modem Support](https://github.com/itsDNNS/docsight/wiki/Requesting-Modem-Support) guide first. Driver work usually depends on:

- the full modem model
- firmware version
- a clean HAR capture including the login flow
- the DOCSIS status page screenshot
- debug logs when login or polling fails

Without that data, modem support requests usually stall.

## Build the proof layer

If DOCSight helped you prove packet loss, recurring instability, signal degradation, or a before-and-after change after ISP work, share it in [Show and tell](https://github.com/itsDNNS/docsight/discussions/categories/show-and-tell).

Useful posts include:

- your hardware and deployment setup
- what problem you were tracking
- which DOCSight views or exports helped most
- what changed after a technician visit, modem swap, or escalation

Real setups and real evidence workflows help new users understand what DOCSight is for before they deploy it.
