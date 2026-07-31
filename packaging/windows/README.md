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
from **Start DOCSight** onward and provides a copy action. Once the owner is
ready, the window hides and a notification-area icon remains available.
Closing the browser does not exit DOCSight.

Startup progresses through four visible phases:

1. **Prepare local data**
2. **Start DOCSight**
3. **Wait for readiness**
4. **Open browser**

If the browser opens successfully, the startup window hides after the open
attempt. The tray icon's default/double-click action and **Open DOCSight**
action open the exact active owner URL. **Open log folder** opens the per-user
logs, and **Quit** performs the bounded shutdown described below.

On a German Windows UI these labels are **DOCSight öffnen**,
**Log-Ordner öffnen**, and **Beenden**. Language selection uses the Windows UI
language; English is the documented fallback for every other language or a
detection failure.

If no port is available, readiness times out, the application thread stops, or
the browser or native tray cannot be opened, the launcher remains visible with
plain-language recovery guidance, the local URL, **Retry**, **Open log folder**,
and **Close**. A tray-start failure never hides the only control path. Retry is
startup recovery only and starts a fresh launcher process; normal **Quit**
never launches a replacement.

## Runtime contract

On startup the launcher creates and exports:

| Value | Desktop Preview behavior |
| --- | --- |
| `DATA_DIR` | `%LOCALAPPDATA%\\DOCSight\\data` |
| `MODULES_DIR` | `%LOCALAPPDATA%\\DOCSight\\modules` |
| `WEB_HOST` | `127.0.0.1` |
| `WEB_PORT` | first available port from `8765` through `8775` |
| `DOCSIGHT_DESKTOP_MODE` | `1` |
| authenticated desktop runtime record | `%LOCALAPPDATA%\\DOCSight\\runtime.json` |
| privacy-filtered launcher phase/recovery log | `%LOCALAPPDATA%\\DOCSight\\logs\\launcher.log` |
| application runtime diagnostics | `%LOCALAPPDATA%\\DOCSight\\logs\\runtime.log` |
| one-time tray explanation marker | `%LOCALAPPDATA%\\DOCSight\\tray-notification-v1` |

`launcher.log` is deliberately limited to sanitized launcher events and is
intended to be shareable. `runtime.log` keeps application diagnostics separate;
review it before sharing because runtime records may contain instance-specific
operational details.

If `LOCALAPPDATA` is unavailable, the launcher falls back to
`Path.home() / "AppData" / "Local"` so the same code path is testable outside
Windows.

## Single-instance behavior

Before selecting a port or starting the server, the launcher acquires a
machine-visible Windows named mutex derived from the current user's SID. The
`Global\` namespace makes the mutex visible across Windows sessions for that
same user. Different Windows users derive different mutex names and do not
share a desktop server. If the direct current-user token lookup is unavailable,
the launcher uses an independent process-token SID lookup against its current
process and uses that SID for both ownership validation and mutex identity. If
both SID lookups fail, startup fails safely before creating a mutex. The mutex
name always remains SID-derived.

The owner holds the mutex for its complete lifetime and atomically replaces
`%LOCALAPPDATA%\DOCSight\runtime.json`. The versioned record contains the
process ID, loopback port, application version, Windows process creation time,
and a cryptographically random per-run token. A later launcher reuses the
record only after the PID, process owner, creation time, and token-authenticated
desktop runtime endpoint all match. An ordinary DOCSight-looking `/health`
response is never enough for handoff.

Second and third launches wait at most 10 seconds while the first owner is
starting. Once validated, they open the exact running loopback port and exit
without starting another application server. If an owner crashed, the
abandoned mutex and stale or malformed runtime record are recovered by a later
launch. The public runtime cleanup API removes the record on explicit normal
exit.

If the preferred port is occupied by another service, the launcher walks the
portable preview range and starts once on the next free port. The server always
binds `127.0.0.1`. If the selected port is lost before the server binds, the
launcher performs at most one clean retry in a fresh process.

## Tray and shutdown lifecycle

The owner creates a minimal generated tray image after authenticated readiness.
The first successful tray start shows a one-time notification explaining that
closing the browser leaves DOCSight running and that the tray can reopen or
quit it. The marker is written only after notification succeeds.

Tray callbacks never touch Tk. They enqueue commands at a narrow dispatch
boundary, and the launcher consumes those commands on the Tk thread. The
launcher reads the active URL at command execution time, so tray actions cannot
reopen a stale preferred port.

The platform-neutral server lifecycle in `app/` retains the Waitress server
created by `waitress.create_server()` behind `run()` and `close()`. Dependency
direction stays one-way:

```text
app server lifecycle <- desktop launcher <- Windows tray adapter
```

Quit is idempotent and centralized. It requests server close, waits at most
12 seconds for the application/startup worker and its polling cleanup, then
stops the tray and calls `DesktopInstance.cleanup()`. If the bounded join does
not finish or server close fails, logs contain only stable failure codes and
exception class names; the launcher cleans tray/runtime ownership as far as
possible and uses process exit code 1 as the last resort. It does not retry,
spawn a replacement, or leave a second owner.

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

The local smoke uses the real per-user SID mutex and must not run alongside another DOCSight desktop instance for that account.

The smoke test launches the packaged executable from two parallel launchers,
uses a temporary `LOCALAPPDATA`, and occupies the preferred port with a foreign
listener. It requires one owner on an allowed fallback, validates the exact
runtime schema, PID, process start time, random token, authenticated endpoint,
second/third-launch handoff, and exactly one IPv4 `127.0.0.1` listener owned by
the runtime PID. It also requires `runtime.log` without packaged route/import
failures such as `failed to import routes` or `No module named`, and validates a
real Reports PDF. It then uses a sentinel under the temporary
`%LOCALAPPDATA%\DOCSight` directory. The sentinel is accepted only when
`DOCSIGHT_SKIP_BROWSER=1` and feeds the same centralized quit command as the
real tray. Across two open/setup/quit cycles, the smoke requires process exit,
selected-port closure, `runtime.json` removal, no child or duplicate packaged
process, persisted setup reopening, a second real write, and exclusive reopen
of the resulting `DATA_DIR` files. The deterministic recovery check then
requires fresh **Prepare local data** evidence, proves that restored stale
runtime state is replaced, and confirms a nonzero main-window handle whose
title is exactly `DOCSight`.

The narrowly scoped `DOCSIGHT_SMOKE_INJECT_STARTUP_FAILURE=1`,
`DOCSIGHT_SMOKE_INJECT_BROWSER_FAILURE=1`, and
`DOCSIGHT_SMOKE_INJECT_NO_PORT_FAILURE=1` switches are honored only while
`DOCSIGHT_SKIP_BROWSER=1` is active. They are packaging/manual-QA test
infrastructure and have no effect during normal interactive startup.
`DOCSIGHT_SMOKE_QUIT_SENTINEL` has the same browser-skip gate and is additionally
restricted to a direct child path under the active per-user DOCSight directory.
It is local packaged-smoke infrastructure, not an HTTP endpoint.

The automated smoke verifies non-interactive process, logging, listener, API,
data-reopen, and recovery contracts. A GitHub-hosted runner does not prove that
the notification-area icon is visible or that mouse/menu interaction works.
Use `QA-CHECKLIST.md` for those interactive Windows checks, visual quality, and
DPI scaling.

## Packaging boundary

The Desktop Preview artifact is a Docker-free tryout build for exploring
DOCSight locally on Windows. For continuous 24/7 monitoring, the Docker/NAS/Linux
deployment remains the recommended path.

The `packaging/` tree is not copied into the Docker image. The final Dockerfile
copies only the application/runtime paths it needs, and `.dockerignore` keeps the
Windows packaging tree out of the Docker build context as well.

The runtime adds `pystray` as a small notification-area adapter. Pillow was
already present and supplies the generated preview image; final application
icon and PE version metadata remain separate work.

## Non-goals for this slice

- No WebView shell, auto-start, updater, installer, MSI, or MSIX.
- No final application icon or PE version metadata.
- No native Windows ICMP/traceroute diagnostics.
- No code-signing integration while provider onboarding is pending.
