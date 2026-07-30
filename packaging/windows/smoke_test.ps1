[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$BundleDir,
    [Parameter(Mandatory = $true)][string]$ExpectedVersion,
    [int]$Port = 8765,
    [int]$TimeoutSeconds = 60
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Net.Http

$BundleDir = [System.IO.Path]::GetFullPath($BundleDir)
$SourceExecutable = Join-Path $BundleDir "DOCSight.exe"
if (-not (Test-Path $SourceExecutable)) {
    throw "DOCSight executable not found: $SourceExecutable"
}

$SmokeRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("DOCSight smoke " + [char]0x00FC + " " + [guid]::NewGuid().ToString("N"))
$LaunchBundleDir = Join-Path $SmokeRoot "Packaged App"
$Executable = Join-Path $LaunchBundleDir "DOCSight.exe"
$LocalAppData = Join-Path $SmokeRoot "LocalAppData"

$PreviousLocalAppData = $env:LOCALAPPDATA
$PreviousWebPort = $env:WEB_PORT
$PreviousSkipBrowser = $env:DOCSIGHT_SKIP_BROWSER
$PreviousInjectedStartupFailure = $env:DOCSIGHT_SMOKE_INJECT_STARTUP_FAILURE
$PreviousInjectedBrowserFailure = $env:DOCSIGHT_SMOKE_INJECT_BROWSER_FAILURE
$PreviousInjectedNoPortFailure = $env:DOCSIGHT_SMOKE_INJECT_NO_PORT_FAILURE
$Process = $null
$HttpHandler = $null
$HttpClient = $null
$LauncherLogFile = Join-Path $LocalAppData "DOCSight\logs\launcher.log"
$RuntimeLogFile = Join-Path $LocalAppData "DOCSight\logs\runtime.log"
$HealthUrl = "http://127.0.0.1:$Port/health"
$ReportUrl = "http://127.0.0.1:$Port/api/report"
$ConfigUrl = "http://127.0.0.1:$Port/api/config"

function Write-SmokeLog {
    if (Test-Path -LiteralPath $LauncherLogFile) {
        Write-Host "--- DOCSight launcher log ---"
        Get-Content -LiteralPath $LauncherLogFile -Tail 200 | ForEach-Object { Write-Host $_ }
        Write-Host "--- end DOCSight launcher log ---"
    } else {
        Write-Host "DOCSight launcher log not found: $LauncherLogFile"
    }

    if (Test-Path -LiteralPath $RuntimeLogFile) {
        Write-Host "--- DOCSight runtime log ---"
        Get-Content -LiteralPath $RuntimeLogFile -Tail 200 | ForEach-Object { Write-Host $_ }
        Write-Host "--- end DOCSight runtime log ---"
    } else {
        Write-Host "DOCSight runtime log not found: $RuntimeLogFile"
    }
}

function Get-PeMachine {
    param([Parameter(Mandatory = $true)][string]$Path)

    $Stream = [System.IO.File]::OpenRead($Path)
    $Reader = [System.IO.BinaryReader]::new($Stream)
    try {
        $Stream.Seek(0x3C, [System.IO.SeekOrigin]::Begin) | Out-Null
        $PeOffset = $Reader.ReadInt32()
        $Stream.Seek($PeOffset, [System.IO.SeekOrigin]::Begin) | Out-Null
        if ($Reader.ReadUInt32() -ne 0x00004550) {
            throw "DOCSight.exe does not contain a valid PE signature."
        }
        return $Reader.ReadUInt16()
    } finally {
        $Reader.Dispose()
        $Stream.Dispose()
    }
}

function Invoke-SmokeHttpRequest {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [ValidateSet("GET", "POST")][string]$Method = "GET",
        [string]$JsonBody
    )

    $Request = [System.Net.Http.HttpRequestMessage]::new(
        [System.Net.Http.HttpMethod]::new($Method),
        [System.Uri]::new($Url)
    )
    try {
        if ($PSBoundParameters.ContainsKey("JsonBody")) {
            $Request.Content = [System.Net.Http.StringContent]::new(
                $JsonBody,
                [System.Text.Encoding]::UTF8,
                "application/json"
            )
        }

        $Response = $HttpClient.SendAsync($Request).GetAwaiter().GetResult()
        try {
            $Bytes = $Response.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult()
            $ContentType = ""
            if ($null -ne $Response.Content.Headers.ContentType) {
                $ContentType = $Response.Content.Headers.ContentType.MediaType
            }
            return [pscustomobject]@{
                StatusCode = [int]$Response.StatusCode
                ContentType = $ContentType
                Bytes = $Bytes
                Body = [System.Text.Encoding]::UTF8.GetString($Bytes)
            }
        } finally {
            $Response.Dispose()
        }
    } finally {
        $Request.Dispose()
    }
}

try {
    New-Item -ItemType Directory -Force -Path $SmokeRoot | Out-Null
    Copy-Item -LiteralPath $BundleDir -Destination $LaunchBundleDir -Recurse -Force
    New-Item -ItemType Directory -Force -Path $LocalAppData | Out-Null
    if (-not (Test-Path $Executable)) {
        throw "Copied DOCSight executable not found: $Executable"
    }
    if ((Get-PeMachine -Path $Executable) -ne 0x8664) {
        throw "DOCSight.exe is not an AMD64 Windows executable."
    }

    $ExistingListeners = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
    if ($ExistingListeners.Count -gt 0) {
        throw "Smoke port $Port is already in use before DOCSight starts."
    }

    $env:LOCALAPPDATA = $LocalAppData
    $env:WEB_PORT = [string]$Port
    $env:DOCSIGHT_SKIP_BROWSER = "1"
    $env:DOCSIGHT_SMOKE_INJECT_STARTUP_FAILURE = $null
    $env:DOCSIGHT_SMOKE_INJECT_BROWSER_FAILURE = $null
    $env:DOCSIGHT_SMOKE_INJECT_NO_PORT_FAILURE = $null

    $HttpHandler = [System.Net.Http.HttpClientHandler]::new()
    $HttpHandler.UseProxy = $false
    $HttpClient = [System.Net.Http.HttpClient]::new($HttpHandler)
    $HttpClient.Timeout = [TimeSpan]::FromSeconds([Math]::Max(3, $TimeoutSeconds))

    $Process = Start-Process -FilePath $Executable -WorkingDirectory $LaunchBundleDir -PassThru
    $Deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $Payload = $null

    while ((Get-Date) -lt $Deadline) {
        if ($Process.HasExited) {
            Write-SmokeLog
            throw "DOCSight exited before /health became ready with exit code $($Process.ExitCode)."
        }

        try {
            $Payload = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 3
            if ($Payload.status -eq "ok") {
                break
            }
        } catch {
            Start-Sleep -Milliseconds 500
            continue
        }

        Start-Sleep -Milliseconds 500
    }

    if ($null -eq $Payload) {
        Write-SmokeLog
        throw "DOCSight /health did not respond within $TimeoutSeconds seconds."
    }
    if ($Payload.status -ne "ok") {
        Write-SmokeLog
        throw "DOCSight /health returned status '$($Payload.status)' instead of 'ok'."
    }
    if ($Payload.version -ne $ExpectedVersion) {
        Write-SmokeLog
        throw "DOCSight /health returned version '$($Payload.version)' instead of '$ExpectedVersion'."
    }

    $Process.Refresh()
    if ($Process.HasExited) {
        Write-SmokeLog
        throw "DOCSight exited after readiness with exit code $($Process.ExitCode)."
    }
    $Connections = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
    $OwnedLoopbackListeners = @($Connections | Where-Object {
        $_.LocalAddress -eq "127.0.0.1" -and $_.OwningProcess -eq $Process.Id
    })
    if ($Connections.Count -ne 1) {
        $ObservedListeners = ($Connections | ForEach-Object {
            "$($_.LocalAddress) owned by PID $($_.OwningProcess)"
        }) -join "; "
        if ([string]::IsNullOrWhiteSpace($ObservedListeners)) {
            $ObservedListeners = "none"
        }
        Write-SmokeLog
        throw "Expected exactly one listener on smoke port $Port; observed: $ObservedListeners"
    }
    if ($OwnedLoopbackListeners.Count -ne 1) {
        $ObservedListener = "$($Connections[0].LocalAddress) owned by PID $($Connections[0].OwningProcess)"
        Write-SmokeLog
        throw "Expected exactly one 127.0.0.1:$Port listener owned by DOCSight process $($Process.Id); observed: $ObservedListener"
    }

    if (-not (Test-Path -LiteralPath $RuntimeLogFile)) {
        Write-SmokeLog
        throw "DOCSight runtime log not found after packaged startup: $RuntimeLogFile"
    }
    $RuntimeLogText = Get-Content -LiteralPath $RuntimeLogFile -Raw
    if ($RuntimeLogText -match "(?i)failed to import routes|No module named") {
        Write-SmokeLog
        throw "DOCSight runtime log contains packaged route/import failure diagnostics."
    }

    $EmptyReportResponse = Invoke-SmokeHttpRequest -Url $ReportUrl
    if ($EmptyReportResponse.StatusCode -ne 404) {
        Write-SmokeLog
        throw "Expected clean /api/report to return HTTP 404, got $($EmptyReportResponse.StatusCode): $($EmptyReportResponse.Body)"
    }
    try {
        $EmptyReportPayload = $EmptyReportResponse.Body | ConvertFrom-Json
    } catch {
        Write-SmokeLog
        throw "Clean /api/report did not return the Reports module JSON response: $($EmptyReportResponse.Body)"
    }
    if ($EmptyReportPayload.error -ne "No data available") {
        Write-SmokeLog
        throw "Clean /api/report returned unexpected JSON error '$($EmptyReportPayload.error)'."
    }

    $SetupJson = @{modem_type = "generic"} | ConvertTo-Json -Compress
    $SetupResponse = Invoke-SmokeHttpRequest -Url $ConfigUrl -Method "POST" -JsonBody $SetupJson
    if ($SetupResponse.StatusCode -ne 200) {
        Write-SmokeLog
        throw "Generic local setup failed with HTTP $($SetupResponse.StatusCode): $($SetupResponse.Body)"
    }
    try {
        $SetupPayload = $SetupResponse.Body | ConvertFrom-Json
    } catch {
        Write-SmokeLog
        throw "Generic local setup returned invalid JSON: $($SetupResponse.Body)"
    }
    if ($SetupPayload.success -ne $true) {
        Write-SmokeLog
        throw "Generic local setup did not succeed: $($SetupResponse.Body)"
    }

    $PdfResponse = $null
    $LastReportResponse = $null
    $ReportDeadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $ReportDeadline) {
        $LastReportResponse = Invoke-SmokeHttpRequest -Url $ReportUrl
        if ($LastReportResponse.StatusCode -eq 200) {
            $PdfResponse = $LastReportResponse
            break
        }
        if (
            $LastReportResponse.StatusCode -ne 404 -or
            $LastReportResponse.Body -notmatch "No data available"
        ) {
            Write-SmokeLog
            throw "Packaged /api/report failed with HTTP $($LastReportResponse.StatusCode): $($LastReportResponse.Body)"
        }
        Start-Sleep -Milliseconds 500
    }
    if ($null -eq $PdfResponse) {
        Write-SmokeLog
        $LastStatus = if ($null -ne $LastReportResponse) { $LastReportResponse.StatusCode } else { "no response" }
        throw "Packaged /api/report did not produce a PDF within $TimeoutSeconds seconds (last status: $LastStatus)."
    }
    if ($PdfResponse.ContentType -ne "application/pdf") {
        Write-SmokeLog
        throw "Packaged /api/report returned Content-Type '$($PdfResponse.ContentType)' instead of 'application/pdf'."
    }
    if (
        $PdfResponse.Bytes.Length -lt 5 -or
        [System.Text.Encoding]::ASCII.GetString($PdfResponse.Bytes, 0, 5) -ne "%PDF-"
    ) {
        Write-SmokeLog
        throw "Packaged /api/report response does not begin with %PDF-."
    }

    if (-not (Test-Path -LiteralPath $LauncherLogFile)) {
        throw "DOCSight launcher log not found for post-smoke validation: $LauncherLogFile"
    }

    Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
    $FirstProcessStopped = $Process.WaitForExit(10000)
    if (-not $FirstProcessStopped) {
        Write-SmokeLog
        throw "Successful packaged process did not stop before injected recovery validation."
    }
    $Process = $null

    if (Test-Path -LiteralPath $LauncherLogFile) {
        Remove-Item -LiteralPath $LauncherLogFile -Force
    }
    if (Test-Path -LiteralPath $LauncherLogFile) {
        throw "Unable to clear the first launcher's log before injected recovery validation."
    }

    # Packaging-only fault injection is honored by the launcher only while the
    # existing non-interactive browser-skip boundary is active.
    $env:DOCSIGHT_SMOKE_INJECT_STARTUP_FAILURE = "1"
    $Process = Start-Process -FilePath $Executable -WorkingDirectory $LaunchBundleDir -PassThru
    $FailureDeadline = (Get-Date).AddSeconds([Math]::Min(20, $TimeoutSeconds))
    $FailureContractObserved = $false
    $RecoveryWindowObserved = $false
    while ((Get-Date) -lt $FailureDeadline) {
        $Process.Refresh()
        if ($Process.HasExited) {
            Write-SmokeLog
            throw "Injected startup failure exited silently with code $($Process.ExitCode) instead of keeping recovery available."
        }
        if (Test-Path -LiteralPath $LauncherLogFile) {
            $FailureLogText = Get-Content -LiteralPath $LauncherLogFile -Raw
            if (
                $FailureLogText -match "Phase: Prepare local data" -and
                $FailureLogText -match "Recovery available: app_thread_failure" -and
                $FailureLogText -match "failure type: RuntimeError"
            ) {
                $FailureContractObserved = $true
            }
        }
        if (
            $Process.MainWindowHandle -ne [IntPtr]::Zero -and
            $Process.MainWindowTitle -ceq "DOCSight"
        ) {
            $RecoveryWindowObserved = $true
        }
        if ($FailureContractObserved -and $RecoveryWindowObserved) {
            break
        }
        Start-Sleep -Milliseconds 250
    }
    if (-not $FailureContractObserved) {
        Write-SmokeLog
        throw "Injected startup failure did not produce the expected launcher phase and recovery log contract."
    }
    $Process.Refresh()
    if ($Process.HasExited) {
        Write-SmokeLog
        throw "Injected startup failure did not keep the recovery process running."
    }
    if ($Process.MainWindowHandle -eq [IntPtr]::Zero) {
        Write-SmokeLog
        throw "Injected startup failure did not expose a real main window."
    }
    if ($Process.MainWindowTitle -cne "DOCSight") {
        Write-SmokeLog
        throw "Injected startup failure main window title was not exactly 'DOCSight'."
    }

    Write-Host "DOCSight Desktop smoke passed: AMD64 package startup, exactly-one owned loopback listener, runtime imports, Reports PDF, and fresh visible app-thread recovery contracts are valid."
} catch {
    Write-SmokeLog
    throw
} finally {
    if ($null -ne $Process -and -not $Process.HasExited) {
        Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
        $Process.WaitForExit(10000) | Out-Null
    }
    if ($null -ne $HttpClient) {
        $HttpClient.Dispose()
    } elseif ($null -ne $HttpHandler) {
        $HttpHandler.Dispose()
    }

    $env:LOCALAPPDATA = $PreviousLocalAppData
    $env:WEB_PORT = $PreviousWebPort
    $env:DOCSIGHT_SKIP_BROWSER = $PreviousSkipBrowser
    $env:DOCSIGHT_SMOKE_INJECT_STARTUP_FAILURE = $PreviousInjectedStartupFailure
    $env:DOCSIGHT_SMOKE_INJECT_BROWSER_FAILURE = $PreviousInjectedBrowserFailure
    $env:DOCSIGHT_SMOKE_INJECT_NO_PORT_FAILURE = $PreviousInjectedNoPortFailure

    if (Test-Path $SmokeRoot) {
        Remove-Item -Recurse -Force $SmokeRoot -ErrorAction SilentlyContinue
    }
}
