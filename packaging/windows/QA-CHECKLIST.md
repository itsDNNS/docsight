# DOCSight Desktop Preview manual QA checklist

Use this checklist before publishing a Windows Desktop Preview release asset. It covers Windows behaviors that the automated package smoke test cannot fully prove.

## Test setup

Record these values before starting:

| Field | Value |
|---|---|
| DOCSight version / artifact name | |
| ZIP SHA256 verified against `.sha256` | |
| Windows edition and version | |
| Test account type | Standard user / Administrator |
| Browser used | |
| Real modem available | Yes / No |

## Clean-machine install and first start

- [ ] Download `DOCSight-Desktop-Preview-win64-<version>.zip` and the matching `.sha256` file from the release or workflow artifact.
- [ ] Verify the ZIP checksum in PowerShell:

  ```powershell
  Get-FileHash .\DOCSight-Desktop-Preview-win64-<version>.zip -Algorithm SHA256
  Get-Content .\DOCSight-Desktop-Preview-win64-<version>.zip.sha256
  ```

- [ ] Extract the ZIP into a normal user-writable folder such as `Downloads\DOCSight`.
- [ ] Double-click `DOCSight.exe`.
- [ ] If SmartScreen appears, confirm the documented flow works: **More info** → **Run anyway** after checksum verification.
- [ ] A centered DOCSight startup window is visible within **under two seconds** of double-clicking, before slow startup completes.
- [ ] At 100%, 150%, and 200% display scaling, the startup and expanded recovery layouts remain readable without clipped actions.
- [ ] The startup window advances through **Prepare local data**, **Start DOCSight**, **Wait for readiness**, and **Open browser**.
- [ ] The local loopback URL is visible from **Start DOCSight** onward; select **Copy** and paste it into Notepad to verify the exact address.
- [ ] The default browser opens `http://127.0.0.1:<port>/` without requiring PowerShell, Docker, WSL, or admin setup.
- [ ] The UI shows the Desktop Preview badge and first-run notice.
- [ ] A one-time Windows notification explains that closing the browser does not exit DOCSight and that it remains available through the tray.
- [ ] Confirm `%LOCALAPPDATA%\DOCSight\tray-notification-v1` exists after the notification, then launch again and verify the notification is not repeated.

## Tray lifecycle and native language

These checks require an interactive Windows notification area. They are not
proved by the packaged smoke on a GitHub-hosted runner.

- [ ] After readiness, confirm the startup window hides and exactly one DOCSight tray icon remains visible while the owner process runs.
- [ ] Close every DOCSight browser tab/window. Confirm the owner process and selected loopback listener remain running intentionally.
- [ ] Double-click the tray icon and verify the exact active `http://127.0.0.1:<port>/` URL reopens.
- [ ] Open the tray menu and select **Open DOCSight**; verify it opens the same active URL, including when the owner selected a fallback port.
- [ ] Select **Open log folder** and verify Explorer opens `%LOCALAPPDATA%\DOCSight\logs`.
- [ ] On a German Windows UI, verify the labels are **DOCSight öffnen**, **Log-Ordner öffnen**, and **Beenden**.
- [ ] On a non-German Windows UI, verify the fallback labels are **Open DOCSight**, **Open log folder**, and **Quit**.
- [ ] Select **Quit** / **Beenden** and verify the process exits, the selected port closes, and `%LOCALAPPDATA%\DOCSight\runtime.json` is removed.
- [ ] Start and quit a second time, then confirm no duplicate process, child process, listener, runtime record, database lock, or other file-handle leak remains.
- [ ] If tray startup is deliberately made unavailable in a development build, verify the sanitized startup/recovery window is visible and remains the control path.

## Startup recovery

Run controlled recovery checks from PowerShell in the extracted bundle directory. Use one command block at a time, close the recovery window afterward, and remove the variables before the next normal launch.

**Application-thread failure**

```powershell
$env:DOCSIGHT_SKIP_BROWSER = "1"
$env:DOCSIGHT_SMOKE_INJECT_STARTUP_FAILURE = "1"
.\DOCSight.exe
Remove-Item Env:DOCSIGHT_SMOKE_INJECT_STARTUP_FAILURE, Env:DOCSIGHT_SKIP_BROWSER -ErrorAction SilentlyContinue
```

**No free preview port**

```powershell
$env:DOCSIGHT_SKIP_BROWSER = "1"
$env:DOCSIGHT_SMOKE_INJECT_NO_PORT_FAILURE = "1"
.\DOCSight.exe
Remove-Item Env:DOCSIGHT_SMOKE_INJECT_NO_PORT_FAILURE, Env:DOCSIGHT_SKIP_BROWSER -ErrorAction SilentlyContinue
```

**Browser-open failure after readiness**

```powershell
$env:DOCSIGHT_SKIP_BROWSER = "1"
$env:DOCSIGHT_SMOKE_INJECT_BROWSER_FAILURE = "1"
.\DOCSight.exe
Remove-Item Env:DOCSIGHT_SMOKE_INJECT_BROWSER_FAILURE, Env:DOCSIGHT_SKIP_BROWSER -ErrorAction SilentlyContinue
```

These switches are ignored unless `DOCSIGHT_SKIP_BROWSER=1` is present.

The release smoke on `windows-latest` separately requires exactly one listener
on its selected fallback port and exactly one process-owned IPv4 loopback
listener. It occupies the preferred port with a foreign listener, races two
launchers, validates `runtime.json` and its authenticated endpoint, and checks
that second and third launches exit after handoff. It also requires
`runtime.log` without route/import degradation, deletes the successful
launcher's `launcher.log` before checking fresh **Prepare local data** evidence,
proves stale runtime replacement, and requires the recovery process to expose a
nonzero main-window handle with the title exactly `DOCSight`. It also performs
two non-interactive open/setup/graceful-quit cycles through a local sentinel
that shares the tray command path. Each cycle requires process exit, port
closure, runtime-state removal, no child or duplicate packaged process, and
successful exclusive reopen of created `DATA_DIR` files.

- [ ] Capture one screenshot of the normal immediate startup status.
- [ ] Run the application-thread failure check and capture a screenshot showing readable, plain-language recovery without exception details.
- [ ] Run the no-port check and verify the address is marked unavailable and **Copy** is disabled. In other error states with a selected port, verify the local URL and **Copy** action still work.
- [ ] Select **Open log folder** and confirm Explorer opens `%LOCALAPPDATA%\DOCSight\logs` with `launcher.log` and `runtime.log` present.
- [ ] Treat sanitized `launcher.log` as shareable launcher evidence. Review the separate `runtime.log` diagnostics before sharing them because they may contain instance-specific details.
- [ ] Select **Retry** and confirm a fresh launcher starts from **Prepare local data** without leaving the prior `DOCSight.exe` process running.
- [ ] Run the browser-open failure check and verify the recovery window remains visible; copy the URL into a browser and confirm the ready local app is usable.
- [ ] Select **Close** on an error surface and confirm it uses the same shutdown path and the launcher process exits.
- [ ] Review `launcher.log` after normal quit. The server close is followed by at most a 12-second wait for application/startup and polling cleanup, then tray stop and runtime cleanup.
- [ ] In a development-only forced timeout check, confirm logs expose only stable codes/exception class names and the process exits with code 1 without starting a replacement.

## Product click-through

- [ ] Complete or skip through the setup wizard without errors.
- [ ] Enable Demo Mode and verify the dashboard loads with realistic demo data.
- [ ] Open the glossary and verify term search/selection works.
- [ ] Open the Evidence Journey and verify the visible checklist/export surfaces load.
- [ ] Open Settings and verify the Desktop Preview badge links to the Desktop Preview documentation.
- [ ] Dismiss the Desktop Preview notice, reload the page, and verify the persistent badge remains while the notice stays dismissed.

## Monitoring behavior

- [ ] If supported modem hardware is available, configure the modem and run one poll from the Windows PC.
- [ ] Verify Connection Monitor uses the documented Desktop Preview behavior: TCP-based checks rather than native ICMP.
- [ ] Put the PC to sleep or hibernate while DOCSight is running, resume it, and confirm collection paused during sleep and continues after resume.

## Process and data location

- [ ] Launch `DOCSight.exe` a second time and a third time while the first instance is running; both should reuse/open the exact existing local port, exit successfully, and start no additional server.
- [ ] Start two launchers as close together as practical and confirm only one owner/listener remains after readiness.
- [ ] With a temporary loopback listener occupying port `8765`, start DOCSight and confirm it starts once on an allowed fallback from `8766` through `8775` without adopting the foreign service.
- [ ] Confirm the only DOCSight listener is IPv4 `127.0.0.1`; no wildcard, LAN, or IPv6 listener is present.
- [ ] Inspect `%LOCALAPPDATA%\DOCSight\runtime.json` and confirm it has schema version, owner PID, selected port, application version, process start time, and a long random instance token.
- [ ] End the owner process, leave `runtime.json` in place, and start DOCSight again; confirm the new owner replaces the stale PID, start time, and token.
- [ ] Replace `runtime.json` with malformed JSON while DOCSight is stopped, then start again and confirm the malformed record is recovered.
- [ ] If multiple interactive sessions are available for one Windows account, start from the second session and confirm it reuses the same owner. Confirm a different Windows account does not reuse that server.
- [ ] Verify logs and data are created under `%LOCALAPPDATA%\DOCSight`.
- [ ] Quit DOCSight from the tray and confirm the process exits cleanly.
- [ ] Delete the extracted Desktop Preview folder.
- [ ] Delete `%LOCALAPPDATA%\DOCSight` when a full uninstall/reset is intended.
- [ ] Re-extract and start again to confirm a clean first-run state.

## Result notes

| Area | Pass / Fail | Notes |
|---|---|---|
| Checksum and extraction | | |
| Double-click startup | | |
| Immediate status under two seconds | | |
| Startup phases and URL copy | | |
| Error screenshot and safe copy | | |
| Retry and prior-process cleanup | | |
| Open log folder / `launcher.log` | | |
| Browser-open failure fallback | | |
| Tray visibility / default action / menu | | |
| German labels / English fallback | | |
| One-time tray notification | | |
| Graceful quit / second-cycle leak check | | |
| SmartScreen flow | | |
| Wizard / Demo Mode | | |
| Dashboard / glossary / evidence | | |
| Real modem poll, if available | | |
| TCP Connection Monitor behavior | | |
| Sleep / resume behavior | | |
| Single-instance launch | | |
| Data location and uninstall | | |
