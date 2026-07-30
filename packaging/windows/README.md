# DOCSight Desktop Preview for Windows

This directory contains the Windows Desktop Preview launcher and portable build
scripts. Windows-specific startup and packaging stay here so DOCSight's core
`app/` runtime remains platform-neutral.

## Entrypoint

Run from the repository root during development:

```powershell
python packaging/windows/docsight_desktop.py
```

The launcher first paints a compact native startup window, then prepares a
per-user runtime tree, starts DOCSight on loopback, and opens the default
browser when `/health` is ready. The window shows the current local address
from **Start DOCSight** onward and provides a copy action.

Startup progresses through four visible phases:

1. **Prepare local data**
2. **Start DOCSight**
3. **Wait for readiness**
4. **Open browser**

If the browser opens successfully, the startup window closes after the open
attempt. If no port is available, readiness times out, the application thread
stops, or the browser cannot be opened, the launcher remains visible with
plain-language recovery guidance, the local URL, **Retry**, **Open log folder**,
and **Close**. Retry starts a fresh launcher process so a previous local server
cannot be retained by the same process.

## Runtime contract

On startup the launcher creates and exports:

| Value | Desktop Preview behavior |
| --- | --- |
| `DATA_DIR` | `%LOCALAPPDATA%\\DOCSight\\data` |
| `MODULES_DIR` | `%LOCALAPPDATA%\\DOCSight\\modules` |
| `WEB_HOST` | `127.0.0.1` |
| `WEB_PORT` | first available port from `8765` through `8775` |
| `DOCSIGHT_DESKTOP_MODE` | `1` |
| privacy-filtered launcher phase/recovery log | `%LOCALAPPDATA%\\DOCSight\\logs\\launcher.log` |
| application runtime diagnostics | `%LOCALAPPDATA%\\DOCSight\\logs\\runtime.log` |

`launcher.log` is deliberately limited to sanitized launcher events and is
intended to be shareable. `runtime.log` keeps application diagnostics separate;
review it before sharing because runtime records may contain instance-specific
operational details.

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

Current preview artifacts are unsigned while provider onboarding is pending.
The matching `.sha256` release asset is available for optional integrity checks.
See the [code signing policy](../../CODE_SIGNING.md) for the onboarding status,
intended release scope, and verification guidance.

The build uses a Windows-resolved, hash-pinned runtime install from
`requirements-runtime-windows.txt` and a cross-platform, hash-pinned build-tool
install from `requirements-build.txt`. The generated `VERSION` file is bundled
next to the packaged `app/` tree so `/health` reports the build version.

## CI automation

The `Windows Desktop Preview` workflow builds the portable package on
`windows-latest`, smoke-tests the built `DOCSight.exe` against
`http://127.0.0.1:<port>/health`, and uploads the ZIP plus `.sha256` as workflow
artifacts. Published releases also receive the ZIP and checksum as release
assets. Workflow artifacts are CI evidence only. Users download the unsigned
portable Preview from [GitHub Releases](https://github.com/itsDNNS/docsight/releases/latest).

For local Windows smoke testing after a build:

```powershell
powershell -ExecutionPolicy Bypass -File packaging/windows/smoke_test.ps1 `
  -BundleDir packaging/windows/dist/DOCSight `
  -ExpectedVersion v2026-07-09.1
```

The smoke test launches the packaged executable, uses a temporary
`LOCALAPPDATA`, skips browser launch via `DOCSIGHT_SKIP_BROWSER=1`, verifies the
`/health` status and version, requires exactly one listener on the smoke port
and exactly one IPv4 `127.0.0.1` listener owned by the launched process, and
requires `runtime.log` without packaged route/import failures such as
`failed to import routes` or `No module named`. It validates a real Reports PDF
and then stops the process. The deterministic recovery check deletes the first
process's `launcher.log` before the injected launch, requires the second process
to write the **Prepare local data** recovery evidence, and confirms a nonzero
main-window handle whose title is exactly `DOCSight`.

The narrowly scoped `DOCSIGHT_SMOKE_INJECT_STARTUP_FAILURE=1`,
`DOCSIGHT_SMOKE_INJECT_BROWSER_FAILURE=1`, and
`DOCSIGHT_SMOKE_INJECT_NO_PORT_FAILURE=1` switches are honored only while
`DOCSIGHT_SKIP_BROWSER=1` is active. They are packaging/manual-QA test
infrastructure and have no effect during normal interactive startup.

The automated smoke verifies process, window-title, logging, listener, API, and
recovery contracts. Use `QA-CHECKLIST.md` for visual quality, DPI scaling, and
interactive action checks.

## Packaging boundary

The Desktop Preview artifact is a Docker-free tryout build for exploring
DOCSight locally on Windows. For continuous 24/7 monitoring, the Docker/NAS/Linux
deployment remains the recommended path.

The `packaging/` tree is not copied into the Docker image. The final Dockerfile
copies only the application/runtime paths it needs, and `.dockerignore` keeps the
Windows packaging tree out of the Docker build context as well.

## Non-goals for this slice

- No tray icon, WebView shell, auto-start, updater, installer, MSI, or MSIX.
- No dedicated shutdown control beyond the launcher recovery surface.
- No native Windows ICMP/traceroute diagnostics.
- No code-signing integration while provider onboarding is pending.
