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

## Reverse Proxy

Exposing DOCSight beyond your local network? See the [reverse proxy guide](docs/reverse-proxy.md) for Caddy, Nginx, and Traefik examples with TLS.
