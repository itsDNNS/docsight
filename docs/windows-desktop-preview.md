# DOCSight Desktop Preview for Windows

DOCSight Desktop Preview is a portable Windows build for trying DOCSight without Docker, WSL, PowerShell setup, or a server. It starts DOCSight locally and opens it in your browser.

Use it for first contact, demos, and short local tests. For reliable 24/7 monitoring, use the normal Docker deployment.

## Choose the right Windows path

| Goal | Recommended path |
|---|---|
| Try DOCSight quickly on a Windows PC | Desktop Preview ZIP |
| Explore Demo Mode, the setup wizard, dashboard, glossary, or evidence workflow | Desktop Preview ZIP |
| Monitor your line continuously on a machine that stays awake, or after host restarts | Docker Desktop on an always-awake Windows PC, or another always-on Docker host |
| Run DOCSight on a NAS, mini-PC, server, or homelab | Docker |

## Download and verify

1. Open the DOCSight [GitHub releases](https://github.com/itsDNNS/docsight/releases).
2. Download the Windows Desktop Preview ZIP when a release provides one. The asset name uses this shape:

   ```text
   DOCSight-Desktop-Preview-win64-<version>.zip
   ```

3. Download the matching `.sha256` file.
4. In PowerShell, verify the checksum from the folder where you saved the files:

   ```powershell
   Get-FileHash .\DOCSight-Desktop-Preview-win64-<version>.zip -Algorithm SHA256
   Get-Content .\DOCSight-Desktop-Preview-win64-<version>.zip.sha256
   ```

   The hash values must match.
5. Extract the ZIP to a folder such as `Downloads\DOCSight` or `C:\Tools\DOCSight`.
6. Start `DOCSight.exe`.

## First start and SmartScreen

The preview is a portable app. Early builds may be unsigned. Windows SmartScreen can therefore show an "unrecognized app" warning even when the checksum matches the release checksum.

If you downloaded DOCSight from the official GitHub release and the SHA256 checksum matches, choose **More info** and then **Run anyway**.

DOCSight starts a local web app and opens your default browser. The address is local to your PC, normally similar to:

```text
http://127.0.0.1:8765
```

## What works in the Desktop Preview

The preview uses the same DOCSight web app and is useful for exploring the product:

- Demo Mode.
- Initial setup wizard.
- Dashboard and signal cards.
- Glossary and beginner help.
- Evidence Journey and local diagnostic exports.
- Basic supported-modem polling from your Windows PC.
- Connection Monitor with TCP-based checks.
- Local settings stored on your Windows user profile.

## Known v0 limitations

Desktop Preview is intentionally not full Windows service support yet:

- **Not an always-on monitor.** It runs only while your Windows user session and the DOCSight process are running.
- **Sleep and hibernate pause collection.** If the laptop or PC sleeps, DOCSight cannot poll the modem or record connection samples during that time.
- **No native ICMP probing in v0.** Connection Monitor falls back to TCP probing on Windows. That still shows reachability signals, but it is not the same as raw ICMP ping.
- **No Windows service or autostart setup.** It does not install a background service that starts before login.
- **No auto-update channel.** Download a newer ZIP from GitHub releases when you want to update.
- **No installer, MSIX, or Store package.** The preview is a portable ZIP.
- **Local-only browser app.** It binds to loopback for tryout use, not to your LAN.

For continuous monitoring, use Docker on an always-on machine instead.

## Where data lives

Desktop Preview stores its data under your Windows user profile:

```text
%LOCALAPPDATA%\DOCSight
```

Typical subfolders:

| Folder | Purpose |
|---|---|
| `%LOCALAPPDATA%\DOCSight\data` | Configuration and local monitoring database |
| `%LOCALAPPDATA%\DOCSight\modules` | Community modules and themes |
| `%LOCALAPPDATA%\DOCSight\logs` | Desktop launcher and runtime logs |

## Remove the Desktop Preview

1. Close DOCSight.
2. Delete the extracted Desktop Preview folder.
3. If you also want to remove local data, delete:

   ```text
   %LOCALAPPDATA%\DOCSight
   ```

Deleting the data folder removes configuration and history for the Desktop Preview.

## Move from Desktop Preview to Docker

When you want DOCSight to monitor continuously:

1. Install Docker Desktop or use an always-on Docker host.
2. Follow the [Windows quick start](windows-quick-start.md) or the full [Installation guide](../INSTALL.md).
3. Start DOCSight with a persistent Docker volume:

   ```powershell
   docker run -d --name docsight --restart unless-stopped -p 8765:8765 -v docsight_data:/data ghcr.io/itsdnns/docsight:latest
   ```

Docker remains the recommended path for 24/7 monitoring because it can restart with the host and is easier to run on a machine that stays online.
