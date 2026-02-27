# Reverse Proxy Setup

DOCSight listens on port **8765** by default. A reverse proxy adds TLS encryption and lets you access DOCSight via a proper domain name.

> **Note:** DOCSight already sets security headers (HSTS, CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy). Your proxy does **not** need to duplicate these — doing so can cause conflicts.

DOCSight does not use WebSockets, so no special upgrade configuration is needed.

---

## Cloudflare Tunnel (Recommended)

Cloudflare Tunnel exposes DOCSight to the internet without opening any ports on your firewall. The `cloudflared` daemon creates an outbound-only connection to Cloudflare's edge network, which handles TLS and DDoS protection.

### Prerequisites

1. A domain managed by Cloudflare (free plan works)
2. A [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) created via the Zero Trust dashboard or CLI

### Create a Tunnel

```bash
# Install cloudflared
# See https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/

# Authenticate with your Cloudflare account
cloudflared tunnel login

# Create a tunnel
cloudflared tunnel create docsight

# Route your domain to the tunnel
cloudflared tunnel route dns docsight docsight.example.com
```

This generates a credentials file at `~/.cloudflared/<TUNNEL_ID>.json`.

### Configuration File

Create `~/.cloudflared/config.yml`:

```yaml
tunnel: <TUNNEL_ID>
credentials-file: /home/user/.cloudflared/<TUNNEL_ID>.json

ingress:
  - hostname: docsight.example.com
    service: http://localhost:8765
  - service: http_status:404
```

Start the tunnel:

```bash
cloudflared tunnel run docsight
```

### Docker Compose

```yaml
services:
  cloudflared:
    image: cloudflare/cloudflared:latest
    restart: unless-stopped
    command: tunnel run
    environment:
      - TUNNEL_TOKEN=<your-tunnel-token>

  docsight:
    image: ghcr.io/itsdnns/docsight:latest
    restart: unless-stopped
    expose:
      - "8765"
    volumes:
      - docsight_data:/data

volumes:
  docsight_data:
```

Get `<your-tunnel-token>` from the [Zero Trust dashboard](https://one.dash.cloudflare.com/) under **Networks → Tunnels → Configure**. When using a token, the tunnel configuration (including ingress rules) is managed in the dashboard — no local config file needed.

> **Tip:** Since Cloudflare Tunnel handles TLS termination, DOCSight receives plain HTTP traffic. The `X-Forwarded-Proto` header is set to `https` by Cloudflare automatically.

---

## Caddy

Caddy handles TLS certificates automatically via Let's Encrypt — no extra setup required.

### Caddyfile

```caddyfile
docsight.example.com {
    reverse_proxy localhost:8765 {
        header_up X-Real-IP {remote_host}
        header_up X-Forwarded-For {remote_host}
        header_up X-Forwarded-Proto {scheme}
    }
}
```

That's it. Caddy obtains and renews certificates automatically.

### Docker Compose

```yaml
services:
  caddy:
    image: caddy:2
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile
      - caddy_data:/data

  docsight:
    image: ghcr.io/itsdnns/docsight:latest
    restart: unless-stopped
    expose:
      - "8765"
    volumes:
      - docsight_data:/data

volumes:
  caddy_data:
  docsight_data:
```

---

## Nginx

### Site Configuration

```nginx
server {
    listen 80;
    server_name docsight.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name docsight.example.com;

    ssl_certificate     /etc/letsencrypt/live/docsight.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/docsight.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8765;

        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Obtain certificates with [certbot](https://certbot.eff.org/):

```bash
sudo certbot --nginx -d docsight.example.com
```

### Docker Compose

```yaml
services:
  nginx:
    image: nginx:alpine
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/docsight.conf
      - /etc/letsencrypt:/etc/letsencrypt:ro

  docsight:
    image: ghcr.io/itsdnns/docsight:latest
    restart: unless-stopped
    expose:
      - "8765"
    volumes:
      - docsight_data:/data

volumes:
  docsight_data:
```

---

## Traefik

Traefik uses Docker labels for configuration and handles Let's Encrypt automatically.

### Docker Compose

```yaml
services:
  traefik:
    image: traefik:v3
    restart: unless-stopped
    command:
      - "--providers.docker=true"
      - "--providers.docker.exposedbydefault=false"
      - "--entrypoints.web.address=:80"
      - "--entrypoints.websecure.address=:443"
      - "--entrypoints.web.http.redirections.entrypoint.to=websecure"
      - "--certificatesresolvers.le.acme.tlschallenge=true"
      - "--certificatesresolvers.le.acme.email=you@example.com"
      - "--certificatesresolvers.le.acme.storage=/letsencrypt/acme.json"
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - traefik_certs:/letsencrypt

  docsight:
    image: ghcr.io/itsdnns/docsight:latest
    restart: unless-stopped
    expose:
      - "8765"
    volumes:
      - docsight_data:/data
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.docsight.rule=Host(`docsight.example.com`)"
      - "traefik.http.routers.docsight.entrypoints=websecure"
      - "traefik.http.routers.docsight.tls.certresolver=le"
      - "traefik.http.services.docsight.loadbalancer.server.port=8765"

volumes:
  traefik_certs:
  docsight_data:
```

Replace `you@example.com` with your email and `docsight.example.com` with your domain.

---

## Verifying Your Setup

After starting your proxy, verify the connection:

```bash
curl -I https://docsight.example.com
```

You should see headers like `Strict-Transport-Security` and `X-Frame-Options` in the response — these come from DOCSight itself.
