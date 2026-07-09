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
- [ ] The default browser opens `http://127.0.0.1:<port>/` without requiring PowerShell, Docker, WSL, or admin setup.
- [ ] The UI shows the Desktop Preview badge and first-run notice.

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

- [ ] Launch `DOCSight.exe` a second time while the first instance is running; it should reuse/open the existing local instance instead of starting a conflicting server.
- [ ] Verify logs and data are created under `%LOCALAPPDATA%\DOCSight`.
- [ ] Close DOCSight and confirm the process exits cleanly.
- [ ] Delete the extracted Desktop Preview folder.
- [ ] Delete `%LOCALAPPDATA%\DOCSight` when a full uninstall/reset is intended.
- [ ] Re-extract and start again to confirm a clean first-run state.

## Result notes

| Area | Pass / Fail | Notes |
|---|---|---|
| Checksum and extraction | | |
| Double-click startup | | |
| SmartScreen flow | | |
| Wizard / Demo Mode | | |
| Dashboard / glossary / evidence | | |
| Real modem poll, if available | | |
| TCP Connection Monitor behavior | | |
| Sleep / resume behavior | | |
| Single-instance launch | | |
| Data location and uninstall | | |
