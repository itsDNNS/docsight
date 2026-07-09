# DOCSight Desktop Preview launcher

This directory contains the Windows Desktop Preview launcher groundwork. The
launcher keeps Windows-specific startup behavior outside `app/` so DOCSight's
core web/runtime code remains platform-neutral.

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

## Non-goals for this slice

- No PyInstaller spec or bundled executable yet.
- No tray icon, WebView shell, auto-start, updater, installer, MSI, or MSIX.
- No native Windows ICMP/traceroute diagnostics.
