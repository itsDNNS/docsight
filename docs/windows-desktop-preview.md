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

## Download and start

1. Open the [latest DOCSight release](https://github.com/itsDNNS/docsight/releases/latest).
2. Under **Assets**, download the unsigned portable Windows Desktop Preview ZIP. Its versioned name uses this shape:

   ```text
   DOCSight-Desktop-Preview-win64-<version>.zip
   ```

3. Extract the ZIP to a folder such as `Downloads\DOCSight` or `C:\Tools\DOCSight`.
4. Start `DOCSight.exe`.

You do not need a GitHub account for this download path. PowerShell and checksum verification are optional.

## Optional: verify download integrity

Each Windows Preview ZIP has a matching checksum asset named:

```text
DOCSight-Desktop-Preview-win64-<version>.zip.sha256
```

For an optional integrity check, download that file from the same GitHub release. In PowerShell, run these commands from the folder where you saved both files:

```powershell
$zip = ".\DOCSight-Desktop-Preview-win64-<version>.zip"
$checksumFile = "$zip.sha256"
$checksumText = Get-Content -LiteralPath $checksumFile -Raw
$expectedHash = if ([string]::IsNullOrWhiteSpace($checksumText)) { "" } else { ($checksumText.Trim() -split '\s+', 2)[0] }
$actualHash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash
$checksumMatches = [string]::Equals($actualHash, $expectedHash, [System.StringComparison]::OrdinalIgnoreCase)
$checksumMatches
```

The final command returns `True` only when the ZIP hash matches the first hash value in the checksum file. SHA-256 is hexadecimal, so uppercase and lowercase letters represent the same hash value and are compared case-insensitively. A matching SHA256 checksum verifies download integrity against the published checksum. It does not verify publisher identity and does not replace a code signature.

## First start and SmartScreen

The preview is a portable, unsigned app while signing provider onboarding is pending. Windows SmartScreen can therefore show an "unrecognized app" warning.

If you downloaded DOCSight from the official GitHub release and choose to continue, select **More info** and then **Run anyway**.

DOCSight starts a local web app and opens your default browser. The address is local to your PC, normally similar to:

```text
http://127.0.0.1:8765
```

A small DOCSight startup window appears first. It shows the current local
address with a **Copy** action from **Start DOCSight** onward and reports
progress while it prepares local data, starts DOCSight, waits for readiness,
and attempts to open the browser. After DOCSight is ready and the browser-open
attempt succeeds, the startup window closes.

Starting `DOCSight.exe` again reuses the already-running instance for the same
Windows user. The later launcher waits for authenticated local readiness, opens
the exact existing address, and exits without starting another server. This
also works across multiple signed-in Windows sessions for the same account.
Different Windows users keep separate instances and data.

If startup cannot finish or the browser cannot be opened, the window stays
available instead of exiting silently. You can copy the displayed local
address, choose **Retry** to start a fresh attempt, open the log folder, or
close DOCSight. A browser-open failure does not mean the local app is
unavailable: copy the address into a browser to continue.

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
| `%LOCALAPPDATA%\DOCSight\logs` | Privacy-filtered launcher diagnostics in `launcher.log`; separate application diagnostics in `runtime.log` |
| `%LOCALAPPDATA%\DOCSight\runtime.json` | Versioned single-instance identity; replaced atomically and recovered after crashes |

`launcher.log` contains only sanitized startup/recovery events and is intended
to be shareable. `runtime.log` contains separate application diagnostics;
review it before sharing because it can contain instance-specific operational
details.

`runtime.json` contains the owning PID, selected loopback port, application
version, process creation time, and a random per-run token. A launcher adopts
that address only when the Windows process owner and creation time match and a
token-authenticated loopback endpoint returns the same identity. Stale PIDs,
reused PIDs, foreign listeners, malformed records, and ordinary `/health`
responses are rejected. The record is not a LAN-access credential: the
Desktop Preview remains bound only to `127.0.0.1`.

The per-user mutex uses Windows' machine-visible `Global\` namespace and is
derived from the account SID, so it coordinates the same user across Windows
sessions without sharing a server across users. If the direct token lookup
fails, an independent process-token SID lookup establishes both the current
owner identity and the same SID-derived mutex name. If both SID lookups fail,
startup fails safely before mutex creation; the mutex name always remains
SID-derived.

The release smoke runs later on `windows-latest`; Linux tests only enforce its
static contract. The Windows run occupies the preferred port, races two
launchers, requires one allowed fallback and exactly one IPv4 loopback listener
owned by the validated runtime PID, and checks authenticated second/third
launch handoff. It also requires `runtime.log` without packaged route/import
degradation and deletes the first launcher's log before requiring fresh
**Prepare local data** evidence from the injected recovery process. That
recovery process must replace stale runtime state and expose a nonzero
main-window handle with the title exactly `DOCSight`.

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
