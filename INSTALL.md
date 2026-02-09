# Installation Guide

Get DOCSight running in under 10 minutes.

## Table of Contents

- [What You Need](#what-you-need)
- [Choose Your Installation Method](#choose-your-installation-method)
  - [Docker CLI](#docker-cli)
  - [Docker Compose](#docker-compose)
  - [Portainer](#portainer)
  - [Dockhand](#dockhand)
- [First-Time Setup](#first-time-setup)
- [Updating DOCSight](#updating-docsight)
- [Troubleshooting](#troubleshooting)
- [Uninstalling](#uninstalling)

## What You Need

- **A computer or NAS** with Docker installed
- **A DOCSIS cable modem or router** (currently supported: AVM FRITZ!Box Cable)
- **Your modem/router login credentials** (the username and password you use to access its web interface)

> **New to Docker?** Docker runs applications in isolated containers. Install it from:
> - **Windows/Mac**: [Docker Desktop](https://www.docker.com/products/docker-desktop/)
> - **Synology NAS**: Search for "Container Manager" in Package Center
> - **Linux**: [Docker Engine](https://docs.docker.com/engine/install/)

## Choose Your Installation Method

All four methods create the exact same container. Pick whichever fits your setup:

| Method | Best for |
|---|---|
| [Docker CLI](#docker-cli) | Quick terminal one-liner |
| [Docker Compose](#docker-compose) | Reproducible config file |
| [Portainer](#portainer) | Users with Portainer web UI |
| [Dockhand](#dockhand) | Users with Dockhand web UI |

---

<details>
<summary><h2>Docker CLI</h2></summary>

### Step 1: Open a terminal

- **Windows**: Search for "Command Prompt" or "PowerShell" in the Start menu
- **Mac**: Open "Terminal" from Applications → Utilities
- **Linux**: Open your terminal emulator
- **Synology NAS**: SSH into your NAS or use the built-in terminal

### Step 2: Run this command

```bash
docker run -d \
  --name docsight \
  --restart unless-stopped \
  -p 8765:8765 \
  -v docsight_data:/data \
  ghcr.io/itsdnns/docsight:latest
```

| Flag | What it does |
|---|---|
| `-d` | Runs in the background |
| `--name docsight` | Names the container "docsight" |
| `--restart unless-stopped` | Auto-starts after reboot |
| `-p 8765:8765` | Makes the web UI available on port 8765 |
| `-v docsight_data:/data` | Stores config and history permanently |

### Step 3: Open DOCSight

Open your browser and go to **http://localhost:8765**

> On a NAS or remote machine, replace `localhost` with the machine's IP address, e.g. `http://192.168.178.15:8765`

Now continue with [First-Time Setup](#first-time-setup).

</details>

---

<details>
<summary><h2>Docker Compose</h2></summary>

### Step 1: Create a `docker-compose.yml` file

Create a new folder (e.g. `docsight`) and save this file inside it as `docker-compose.yml`:

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

volumes:
  docsight_data:
```

### Step 2: Start the container

Open a terminal in the folder with your `docker-compose.yml` and run:

```bash
docker compose up -d
```

### Step 3: Open DOCSight

Open your browser and go to **http://localhost:8765**

> On a NAS or remote machine, replace `localhost` with the machine's IP address, e.g. `http://192.168.178.15:8765`

Now continue with [First-Time Setup](#first-time-setup).

</details>

---

<details>
<summary><h2>Portainer</h2></summary>

### Step 1: Open Portainer

Open your Portainer web UI (usually `https://your-host-ip:9443`).

### Step 2: Create a new stack

1. Go to **Stacks** in the left menu
2. Click **Add stack**
3. Give it the name `docsight`
4. In the **Web editor**, paste this YAML:

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

volumes:
  docsight_data:
```

5. Click **Deploy the stack**

### Step 3: Open DOCSight

Open your browser and go to **http://your-host-ip:8765**

Now continue with [First-Time Setup](#first-time-setup).

</details>

---

<details>
<summary><h2>Dockhand</h2></summary>

### Step 1: Open Dockhand

Open your Dockhand web UI in your browser.

### Step 2: Create a new stack

1. Go to **Stacks** in the navigation
2. Click **Create Stack**
3. Give it the name `docsight`
4. In the YAML editor, paste this:

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

volumes:
  docsight_data:
```

5. Click **Deploy**

### Step 3: Open DOCSight

Open your browser and go to **http://your-host-ip:8765**

Now continue with [First-Time Setup](#first-time-setup).

</details>

---

## First-Time Setup

When you open DOCSight for the first time, a setup wizard guides you through the configuration.

![Setup Wizard](docs/screenshots/setup.png)

### Step 1: Modem Connection

> **Recommended: Create a dedicated user**
>
> Instead of using your main admin account, create a separate user for DOCSight on your modem. This way you can rotate or revoke its credentials independently without affecting your admin login.
>
> <details>
> <summary>Example: FRITZ!Box</summary>
>
> 1. Open `http://fritz.box` and log in as admin
> 2. Go to **System** > **FRITZ!Box Users** > **Add User**
> 3. Set username (e.g. `docsight`) and a password
> 4. Enable **only** "Access to FRITZ!Box settings" - disable everything else
> 5. Click **Apply**
>
> Use this new username and password in DOCSight instead of your admin credentials.
>
> *Note: "Access to FRITZ!Box settings" is the only permission DOCSight needs. DOCSight only reads data and never modifies any settings.*
> </details>

| Field | What to enter |
|---|---|
| **Modem URL** | Your modem's web interface address (e.g. `http://192.168.178.1`) |
| **Username** | Your dedicated DOCSight user (or admin username) |
| **Password** | The corresponding password |

Click **Test Connection** to verify DOCSight can reach your router. If successful, continue to the next step.

### Step 2: General Settings

| Field | Description | Default |
|---|---|---|
| **ISP** | Your internet provider name (for reports) | - |
| **Poll Interval** | How often to read channel data (seconds) | `300` (5 min) |
| **History Days** | How many days of snapshots to keep | `7` |
| **Snapshot Time** | When to save the daily snapshot | `03:00` |

### Advanced: MQTT for Home Assistant (optional)

If you use Home Assistant, you can enable MQTT to get per-channel sensors automatically:

| Field | Description |
|---|---|
| **MQTT Host** | Your MQTT broker address (e.g. `192.168.178.15`) |
| **MQTT Port** | `1883` (default) |
| **MQTT User** | Broker username (if required) |
| **MQTT Password** | Broker password (if required) |

### Complete

Click **Complete Setup** - DOCSight starts monitoring immediately. Your dashboard will show channel data after the first poll.

---

<details>
<summary><h2>Updating DOCSight</h2></summary>

Your configuration and history are stored in a Docker volume and survive updates.

### Docker CLI

```bash
docker pull ghcr.io/itsdnns/docsight:latest
docker stop docsight
docker rm docsight
docker run -d --name docsight --restart unless-stopped -p 8765:8765 -v docsight_data:/data ghcr.io/itsdnns/docsight:latest
```

### Docker Compose

```bash
docker compose pull
docker compose up -d
```

### Portainer

1. Open the **docsight** stack
2. Click **Update the stack**
3. Enable **Re-pull image**
4. Click **Update**

### Dockhand

1. Open the **docsight** stack
2. Click **Redeploy**

</details>

---

<details>
<summary><h2>Troubleshooting</h2></summary>

<details>
<summary><strong>"Can't open http://localhost:8765"</strong></summary>

- **Is the container running?** Check with `docker ps` - you should see a container named `docsight`
- **On a NAS?** Use the NAS IP address instead of `localhost`, e.g. `http://192.168.178.15:8765`
- **Firewall?** Make sure port 8765 is not blocked

</details>

<details>
<summary><strong>"Test Connection fails"</strong></summary>

- **Is the URL correct?** Try opening your modem's web interface URL in your browser first (e.g. `http://192.168.178.1` for FRITZ!Box).
- **Are the credentials correct?** Use the same username and password you use to log into your modem's web interface.
- **Network access?** The Docker container must be able to reach your modem. If running on a remote server, ensure it's on the same network.

</details>

<details>
<summary><strong>"Port 8765 already in use"</strong></summary>

Another application is using port 8765. Change the port mapping:

```bash
# Docker CLI: change the first number to any free port
docker run -d --name docsight --restart unless-stopped -p 9876:8765 -v docsight_data:/data ghcr.io/itsdnns/docsight:latest
```

```yaml
# Docker Compose / Portainer / Dockhand: change the first number
ports:
  - "9876:8765"
```

Then open `http://localhost:9876` instead.

</details>

<details>
<summary><strong>"Container keeps restarting"</strong></summary>

Check the container logs:

```bash
docker logs docsight
```

The logs usually indicate the problem. Common causes:
- Invalid configuration - delete the volume and start fresh: `docker volume rm docsight_data`
- Network issues reaching the modem

</details>

<details>
<summary><strong>"How do I check if it's working?"</strong></summary>

```bash
docker logs docsight --tail 20
```

You should see log entries about successful polls. If the dashboard shows channel data, everything is working.

</details>

</details>

---

<details>
<summary><h2>Uninstalling</h2></summary>

### Docker CLI / Docker Compose

```bash
docker stop docsight
docker rm docsight
docker volume rm docsight_data
```

### Portainer / Dockhand

1. Open the **docsight** stack
2. Delete the stack

This removes the container and all stored data.

</details>
