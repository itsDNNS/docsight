# Windows 10/11 Quick Start

DOCSight runs on Windows through Docker Desktop. This is still the normal Docker deployment path: Docker Desktop provides the Linux container runtime and DOCSight keeps its data in a Docker volume.

## 1. Install and verify Docker Desktop

1. Install [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop/).
2. During setup, allow Docker Desktop to use **WSL 2** when prompted. Hyper-V also works when your Windows edition and Docker Desktop settings use it.
3. Restart Windows if the installer asks you to.
4. Open Docker Desktop and wait until it says the engine is running.
5. Open **PowerShell** and verify Docker is available:

```powershell
docker --version
```

Then verify the engine is reachable:

```powershell
docker info
```

If `docker --version` works but `docker info` fails, Docker Desktop is installed but the engine is not running yet. Open Docker Desktop and wait for it to finish starting.

## 2. Start DOCSight from PowerShell

Copy and paste this one-line command into PowerShell:

```powershell
docker run -d --name docsight --restart unless-stopped -p 8765:8765 -v docsight_data:/data ghcr.io/itsdnns/docsight:latest
```

What this does:

| Part | Meaning |
|---|---|
| `--name docsight` | Names the container so you can manage it later |
| `--restart unless-stopped` | Starts DOCSight again after Windows or Docker restarts |
| `-p 8765:8765` | Makes the web UI available at `http://localhost:8765` |
| `-v docsight_data:/data` | Keeps configuration and history in a persistent Docker volume |

## 3. Open DOCSight

Open this URL in your browser:

```text
http://localhost:8765
```

The setup wizard lets you choose Demo Mode, a supported DOCSIS modem, or Generic Router mode.

## Optional: try Demo Mode first

If you want to explore DOCSight before connecting a real modem, run a separate demo container:

```powershell
docker run -d --name docsight-demo --restart unless-stopped -p 8765:8765 -e DEMO_MODE=true ghcr.io/itsdnns/docsight:latest
```

Use either the demo container or the normal `docsight` container on port `8765`, not both at the same time.

## Windows troubleshooting

| Symptom | What to check | Fix |
|---|---|---|
| `docker` is not recognized | Docker Desktop is not installed or PowerShell was opened before installation finished | Install Docker Desktop, restart Windows if requested, then open a new PowerShell window |
| `docker info` says it cannot connect to the Docker daemon | Docker Desktop is installed but the engine is not running | Open Docker Desktop and wait until the engine is running, then retry `docker info` |
| Docker Desktop asks for WSL 2 or fails during startup | WSL 2 integration is missing or disabled | In Docker Desktop settings, enable WSL 2 integration. If Windows prompts you to install WSL components, complete that setup and restart |
| Port `8765` is already allocated or already in use | Another app or an older DOCSight container is using the port | Stop the old container with `docker stop docsight`, or run DOCSight on another local port such as `-p 8766:8765` and open `http://localhost:8766` |
| The name `docsight` is already in use | A previous container with the same name already exists | Start it with `docker start docsight`, or remove it with `docker rm docsight` before running the command again. Removing the container does not remove the `docsight_data` volume |
| `http://localhost:8765` does not open | The container may still be starting, may have exited, or may be on a different port | Check `docker ps -a`, then inspect logs with `docker logs docsight`. If you used `-p 8766:8765`, open `http://localhost:8766` |
| A copied multi-line command fails in PowerShell | Bash line continuations with `\` do not work in PowerShell | Use the one-line PowerShell command above |

## Updating later

When a new DOCSight release is available, update the container image and recreate the container while keeping the same `docsight_data` volume. The full update flow is covered in the [Installation guide](https://github.com/itsDNNS/docsight/wiki/Installation).
