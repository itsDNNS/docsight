# DOCSight Desktop Preview for Windows

This directory contains the Windows Desktop Preview launcher and portable build
scripts. Windows-specific startup and packaging stay here so DOCSight's core
`app/` runtime remains platform-neutral.

## Entrypoint

Run from the repository root during development:

```powershell
python packaging/windows/docsight_desktop.py
```

The launcher prepares a per-user runtime tree, starts DOCSight on loopback, and
opens the default browser when `/health` is ready.

## Runtime contract

On startup the launcher creates and exports:

| Value | Desktop Preview behavior |
| --- | --- |
| `DATA_DIR` | `%LOCALAPPDATA%\\DOCSight\\data` |
| `MODULES_DIR` | `%LOCALAPPDATA%\\DOCSight\\modules` |
| `WEB_HOST` | `127.0.0.1` |
| `WEB_PORT` | first available port from `8765` through `8775` |
| `DOCSIGHT_DESKTOP_MODE` | `1` |
| log file | `%LOCALAPPDATA%\\DOCSight\\logs\\docsight.log` |

If `LOCALAPPDATA` is unavailable, the launcher falls back to
`Path.home() / "AppData" / "Local"` so the same code path is testable outside
Windows.

## Single-instance behavior

Before starting a new process, the launcher probes the preferred port's
`/health` endpoint. If the response looks like DOCSight (`status: ok` and a
`version` field), it opens the browser to that existing instance and exits.

If the preferred port is occupied by another service, the launcher walks the
portable preview range and starts on the next free port.

## Portable ZIP build

Prerequisites:

- Windows x64
- Python 3.13 x64 available through the Python Launcher (`py -3.13`)
- Git, when building from a checkout and deriving the version automatically
- No administrator rights required

Build from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File packaging/windows/build.ps1
```

Optional parameters:

```powershell
powershell -ExecutionPolicy Bypass -File packaging/windows/build.ps1 -Version v2026-07-09.1
powershell -ExecutionPolicy Bypass -File packaging/windows/build.ps1 -PythonLauncher python -PythonVersion ""
```

Outputs:

```text
packaging/windows/dist/DOCSight/
packaging/windows/dist/DOCSight-Desktop-Preview-win64-<version>.zip
packaging/windows/dist/DOCSight-Desktop-Preview-win64-<version>.zip.sha256
```

The build uses a Windows-resolved, hash-pinned runtime install from
`requirements-runtime-windows.txt` and a cross-platform, hash-pinned build-tool
install from `requirements-build.txt`. The generated `VERSION` file is bundled
next to the packaged `app/` tree so `/health` reports the build version.

## Packaging boundary

The Desktop Preview artifact is a Docker-free tryout build for exploring
DOCSight locally on Windows. For continuous 24/7 monitoring, the Docker/NAS/Linux
deployment remains the recommended path.

The `packaging/` tree is not copied into the Docker image. The final Dockerfile
copies only the application/runtime paths it needs, and `.dockerignore` keeps the
Windows packaging tree out of the Docker build context as well.

## Non-goals for this slice

- No GitHub Actions automation yet.
- No tray icon, WebView shell, auto-start, updater, installer, MSI, or MSIX.
- No native Windows ICMP/traceroute diagnostics.
- No code signing.
