# Installation Guide

👉 **See the [full installation guide](https://github.com/itsDNNS/docsight/wiki/Installation) in the wiki.**

Covers Docker Run, Docker Compose, Portainer, Synology NAS, Unraid, updating, and troubleshooting.

## Quick Start

```bash
docker run -d \
  --name docsight \
  --restart unless-stopped \
  -p 8765:8765 \
  -v docsight_data:/data \
  ghcr.io/itsdnns/docsight:latest
```

Open `http://localhost:8765` and follow the setup wizard.

## Bare-Metal / systemd

If you run DOCSight outside of Docker (e.g. as a systemd service), you need to compile and install the native helpers manually. These are tiny C programs that need setuid root because ICMP raw sockets require elevated privileges.

```bash
# Install build dependencies (Debian/Ubuntu)
sudo apt install gcc libffi-dev libjpeg62-turbo-dev zlib1g-dev

# Install Python dependencies
pip install -r requirements.txt

# Compile and install the ICMP helpers
sudo gcc -O2 -Wall -o /usr/local/bin/docsight-icmp-helper tools/icmp_probe_helper.c
sudo gcc -O2 -Wall -o /usr/local/bin/docsight-traceroute-helper tools/traceroute_helper.c

# Set ownership and setuid bit
sudo chown root:root /usr/local/bin/docsight-icmp-helper /usr/local/bin/docsight-traceroute-helper
sudo chmod 4755 /usr/local/bin/docsight-icmp-helper /usr/local/bin/docsight-traceroute-helper
```

Without these binaries, traceroute and ICMP probes will log errors but the rest of DOCSight works fine.

## Reverse Proxy

Exposing DOCSight beyond your local network? See the [reverse proxy guide](https://github.com/itsDNNS/docsight/wiki/Reverse-Proxy) for Caddy, Nginx, and Traefik examples with TLS.
