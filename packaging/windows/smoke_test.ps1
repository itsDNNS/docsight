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
$PreviousSmokeQuitSentinel = $env:DOCSIGHT_SMOKE_QUIT_SENTINEL
$Process = $null
$LaunchOne = $null
$LaunchTwo = $null
$FollowerProcess = $null
$ThirdProcess = $null
$CycleTwoProcess = $null
$ForeignListener = $null
$HttpHandler = $null
$HttpClient = $null
$LauncherLogFile = Join-Path $LocalAppData "DOCSight\logs\launcher.log"
$RuntimeLogFile = Join-Path $LocalAppData "DOCSight\logs\runtime.log"
$RuntimeStateFile = Join-Path $LocalAppData "DOCSight\runtime.json"
$SmokeQuitSentinel = Join-Path $LocalAppData "DOCSight\smoke-quit.signal"
$HealthUrl = $null
$ReportUrl = $null
$ConfigUrl = $null
$DesktopRuntimeUrl = $null

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
        [string]$JsonBody,
        [string]$BearerToken
    )

    $Request = [System.Net.Http.HttpRequestMessage]::new(
        [System.Net.Http.HttpMethod]::new($Method),
        [System.Uri]::new($Url)
    )
    try {
        if ($PSBoundParameters.ContainsKey("BearerToken")) {
            $Request.Headers.Authorization = [System.Net.Http.Headers.AuthenticationHeaderValue]::new(
                "Bearer",
                $BearerToken
            )
        }
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

function Assert-NoPackagedProcess {
    $PackagedProcesses = @(Get-CimInstance Win32_Process | Where-Object {
        -not [string]::IsNullOrWhiteSpace($_.ExecutablePath) -and
        [string]::Equals(
            [System.IO.Path]::GetFullPath($_.ExecutablePath),
            $Executable,
            [System.StringComparison]::OrdinalIgnoreCase
        )
    })
    if ($PackagedProcesses.Count -ne 0) {
        throw "A packaged DOCSight process remained after graceful quit."
    }
}

function Assert-NoOwnerChildren {
    param([Parameter(Mandatory = $true)][System.Diagnostics.Process]$Owner)

    $Children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $($Owner.Id)")
    if ($Children.Count -ne 0) {
        throw "The DOCSight owner created an unexpected child process."
    }
}

function Assert-DataFilesReopen {
    $DataFiles = @(Get-ChildItem -LiteralPath (Join-Path $LocalAppData "DOCSight\data") -File)
    if ($DataFiles.Count -eq 0) {
        throw "Graceful smoke did not create any DATA_DIR files."
    }
    foreach ($DataFile in $DataFiles) {
        $Stream = [System.IO.File]::Open(
            $DataFile.FullName,
            [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::ReadWrite,
            [System.IO.FileShare]::None
        )
        $Stream.Dispose()
    }
}

function Request-GracefulQuit {
    param(
        [Parameter(Mandatory = $true)][System.Diagnostics.Process]$Owner,
        [Parameter(Mandatory = $true)][int]$RuntimePort,
        [Parameter(Mandatory = $true)][string]$CycleName
    )

    Assert-NoOwnerChildren -Owner $Owner
    [System.IO.File]::WriteAllText(
        $SmokeQuitSentinel,
        "quit",
        [System.Text.UTF8Encoding]::new($false)
    )
    if (-not $Owner.WaitForExit(25000)) {
        Write-SmokeLog
        throw "$CycleName did not exit through the graceful quit command."
    }
    if ($Owner.ExitCode -ne 0) {
        Write-SmokeLog
        throw "$CycleName graceful quit returned exit code $($Owner.ExitCode)."
    }

    $PortCloseDeadline = (Get-Date).AddSeconds(10)
    do {
        $RemainingListeners = @(
            Get-NetTCPConnection -State Listen -LocalPort $RuntimePort -ErrorAction SilentlyContinue
        )
        if ($RemainingListeners.Count -eq 0) {
            break
        }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $PortCloseDeadline)

    if ($RemainingListeners.Count -ne 0) {
        throw "$CycleName left its selected port listening after graceful quit."
    }
    if (Test-Path -LiteralPath $RuntimeStateFile) {
        throw "$CycleName left runtime.json after graceful quit."
    }
    Assert-NoPackagedProcess
    Assert-DataFilesReopen
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
    $ForeignListener = [System.Net.Sockets.TcpListener]::new(
        [System.Net.IPAddress]::Loopback,
        $Port
    )
    $ForeignListener.Start()

    $env:LOCALAPPDATA = $LocalAppData
    $env:WEB_PORT = [string]$Port
    $env:DOCSIGHT_SKIP_BROWSER = "1"
    $env:DOCSIGHT_SMOKE_INJECT_STARTUP_FAILURE = $null
    $env:DOCSIGHT_SMOKE_INJECT_BROWSER_FAILURE = $null
    $env:DOCSIGHT_SMOKE_INJECT_NO_PORT_FAILURE = $null
    $env:DOCSIGHT_SMOKE_QUIT_SENTINEL = $SmokeQuitSentinel

    $HttpHandler = [System.Net.Http.HttpClientHandler]::new()
    $HttpHandler.UseProxy = $false
    $HttpClient = [System.Net.Http.HttpClient]::new($HttpHandler)
    $HttpClient.Timeout = [TimeSpan]::FromSeconds([Math]::Max(3, $TimeoutSeconds))

    # Start two launchers back-to-back while a foreign listener owns the
    # preferred port. Exactly one launcher must become the fallback-port owner.
    $LaunchOne = Start-Process -FilePath $Executable -WorkingDirectory $LaunchBundleDir -PassThru
    $LaunchTwo = Start-Process -FilePath $Executable -WorkingDirectory $LaunchBundleDir -PassThru
    $Deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $Payload = $null
    $RuntimeState = $null
    $DesktopRuntimePayload = $null

    while ((Get-Date) -lt $Deadline) {
        $LaunchOne.Refresh()
        $LaunchTwo.Refresh()
        if ($LaunchOne.HasExited -and $LaunchTwo.HasExited) {
            Write-SmokeLog
            throw "Both parallel DOCSight launchers exited before runtime readiness."
        }

        try {
            if (Test-Path -LiteralPath $RuntimeStateFile) {
                $RuntimeState = Get-Content -LiteralPath $RuntimeStateFile -Raw | ConvertFrom-Json
                $RuntimePort = [int]$RuntimeState.port
                $HealthUrl = "http://127.0.0.1:$RuntimePort/health"
                $ReportUrl = "http://127.0.0.1:$RuntimePort/api/report"
                $ConfigUrl = "http://127.0.0.1:$RuntimePort/api/config"
                $DesktopRuntimeUrl = "http://127.0.0.1:$RuntimePort/desktop-runtime"
                $Payload = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 3
                $DesktopRuntimeResponse = Invoke-SmokeHttpRequest `
                    -Url $DesktopRuntimeUrl `
                    -BearerToken ([string]$RuntimeState.instance_token)
                if ($DesktopRuntimeResponse.StatusCode -eq 200) {
                    $DesktopRuntimePayload = $DesktopRuntimeResponse.Body | ConvertFrom-Json
                }
                if (
                    $Payload.status -eq "ok" -and
                    $null -ne $DesktopRuntimePayload -and
                    $DesktopRuntimePayload.status -eq "ok"
                ) {
                    break
                }
            }
        } catch {
            Start-Sleep -Milliseconds 500
            continue
        }

        Start-Sleep -Milliseconds 500
    }

    if ($null -eq $RuntimeState) {
        Write-SmokeLog
        throw "DOCSight did not publish runtime.json within $TimeoutSeconds seconds."
    }
    if ($null -eq $Payload -or $null -eq $DesktopRuntimePayload) {
        Write-SmokeLog
        throw "DOCSight runtime endpoints did not become ready within $TimeoutSeconds seconds."
    }
    if ($Payload.status -ne "ok") {
        Write-SmokeLog
        throw "DOCSight /health returned status '$($Payload.status)' instead of 'ok'."
    }
    if ($Payload.version -ne $ExpectedVersion) {
        Write-SmokeLog
        throw "DOCSight /health returned version '$($Payload.version)' instead of '$ExpectedVersion'."
    }

    $RuntimeFields = @($RuntimeState.PSObject.Properties.Name | Sort-Object)
    $ExpectedRuntimeFields = @(
        "application_version",
        "instance_token",
        "pid",
        "port",
        "process_start_time",
        "schema_version"
    ) | Sort-Object
    $RuntimeFieldDifference = @(Compare-Object $RuntimeFields $ExpectedRuntimeFields)
    if ($RuntimeFieldDifference.Count -ne 0) {
        Write-SmokeLog
        throw "runtime.json does not contain the exact versioned desktop runtime schema."
    }
    if ([int]$RuntimeState.schema_version -ne 1) {
        throw "runtime.json schema_version is not 1."
    }
    if ([int]$RuntimeState.port -eq $Port) {
        throw "DOCSight adopted the foreign listener on preferred port $Port."
    }
    if ([int]$RuntimeState.port -lt 8765 -or [int]$RuntimeState.port -gt 8775) {
        throw "DOCSight selected fallback port '$($RuntimeState.port)' outside 8765-8775."
    }
    if ([string]$RuntimeState.application_version -ne $ExpectedVersion) {
        throw "runtime.json application version does not match the packaged build."
    }
    if ([string]$RuntimeState.instance_token -notmatch "^[A-Za-z0-9_-]{43,128}$") {
        throw "runtime.json instance token is malformed."
    }

    $ParallelLaunches = @($LaunchOne, $LaunchTwo)
    $OwnerCandidates = @($ParallelLaunches | Where-Object {
        $_.Id -eq [int]$RuntimeState.pid
    })
    if ($OwnerCandidates.Count -ne 1) {
        Write-SmokeLog
        throw "runtime.json PID does not identify exactly one parallel launcher."
    }
    $Process = $OwnerCandidates[0]
    $FollowerProcess = @($ParallelLaunches | Where-Object {
        $_.Id -ne $Process.Id
    })[0]
    $Process.Refresh()
    if ($Process.HasExited) {
        Write-SmokeLog
        throw "DOCSight exited after readiness with exit code $($Process.ExitCode)."
    }
    $ExpectedStartTime = $Process.StartTime.ToUniversalTime().ToFileTimeUtc()
    if ([int64]$RuntimeState.process_start_time -ne $ExpectedStartTime) {
        throw "runtime.json process start time does not match its owner process."
    }
    if (
        [int]$DesktopRuntimePayload.pid -ne $Process.Id -or
        [int]$DesktopRuntimePayload.port -ne [int]$RuntimeState.port -or
        [int64]$DesktopRuntimePayload.process_start_time -ne $ExpectedStartTime -or
        [string]$DesktopRuntimePayload.instance_token -cne [string]$RuntimeState.instance_token -or
        [string]$DesktopRuntimePayload.application_version -cne $ExpectedVersion
    ) {
        throw "Authenticated desktop runtime payload does not exactly match runtime.json."
    }

    $RejectedTokenResponse = Invoke-SmokeHttpRequest `
        -Url $DesktopRuntimeUrl `
        -BearerToken (("B" * 43) -join "")
    if ($RejectedTokenResponse.StatusCode -ne 404) {
        throw "Desktop runtime endpoint accepted the wrong instance token."
    }

    if (-not $FollowerProcess.WaitForExit(15000)) {
        throw "The non-owner parallel launcher did not hand off and exit."
    }
    if ($FollowerProcess.ExitCode -ne 0) {
        throw "The non-owner parallel launcher exited with code $($FollowerProcess.ExitCode)."
    }

    $ThirdProcess = Start-Process -FilePath $Executable -WorkingDirectory $LaunchBundleDir -PassThru
    if (-not $ThirdProcess.WaitForExit(15000)) {
        throw "The third launcher did not reuse the running desktop instance."
    }
    if ($ThirdProcess.ExitCode -ne 0) {
        throw "The third launcher exited with code $($ThirdProcess.ExitCode)."
    }
    $StateAfterHandoffs = Get-Content -LiteralPath $RuntimeStateFile -Raw | ConvertFrom-Json
    if (
        [int]$StateAfterHandoffs.pid -ne $Process.Id -or
        [int]$StateAfterHandoffs.port -ne [int]$RuntimeState.port -or
        [string]$StateAfterHandoffs.instance_token -cne [string]$RuntimeState.instance_token
    ) {
        throw "Second or third launch replaced the existing owner's runtime state."
    }

    $RuntimePort = [int]$RuntimeState.port
    $Connections = @(Get-NetTCPConnection -State Listen -LocalPort $RuntimePort -ErrorAction SilentlyContinue)
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
        throw "Expected exactly one listener on runtime port $RuntimePort; observed: $ObservedListeners"
    }
    if ($OwnedLoopbackListeners.Count -ne 1) {
        $ObservedListener = "$($Connections[0].LocalAddress) owned by PID $($Connections[0].OwningProcess)"
        Write-SmokeLog
        throw "Expected exactly one 127.0.0.1:$RuntimePort listener owned by DOCSight process $($Process.Id); observed: $ObservedListener"
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

    $PreviousRuntimeToken = [string]$RuntimeState.instance_token
    $StaleRuntimeJson = Get-Content -LiteralPath $RuntimeStateFile -Raw
    Request-GracefulQuit `
        -Owner $Process `
        -RuntimePort ([int]$RuntimeState.port) `
        -CycleName "First packaged cycle"
    $Process = $null
    $PersistedConfigFile = Join-Path $LocalAppData "DOCSight\data\config.json"
    if (
        -not (Test-Path -LiteralPath $PersistedConfigFile) -or
        (Get-Content -LiteralPath $PersistedConfigFile -Raw) -notmatch '"modem_type"\s*:\s*"generic"'
    ) {
        throw "Second packaged cycle could not reopen the persisted setup."
    }

    # Reopen the same DATA_DIR, prove the persisted setup is readable, perform
    # another real setup write, and quit through the identical command path.
    $CycleTwoProcess = Start-Process -FilePath $Executable -WorkingDirectory $LaunchBundleDir -PassThru
    $Process = $CycleTwoProcess
    $CycleTwoDeadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $CycleTwoState = $null
    $CycleTwoPayload = $null
    while ((Get-Date) -lt $CycleTwoDeadline) {
        $Process.Refresh()
        if ($Process.HasExited) {
            Write-SmokeLog
            throw "Second packaged cycle exited before readiness."
        }
        try {
            if (Test-Path -LiteralPath $RuntimeStateFile) {
                $CycleTwoState = Get-Content -LiteralPath $RuntimeStateFile -Raw | ConvertFrom-Json
                if ([int]$CycleTwoState.pid -eq $Process.Id) {
                    $CycleTwoHealthUrl = "http://127.0.0.1:$([int]$CycleTwoState.port)/health"
                    $CycleTwoPayload = Invoke-RestMethod -Uri $CycleTwoHealthUrl -TimeoutSec 3
                    if ($CycleTwoPayload.status -eq "ok") {
                        break
                    }
                }
            }
        } catch {
            Start-Sleep -Milliseconds 500
            continue
        }
        Start-Sleep -Milliseconds 500
    }
    if ($null -eq $CycleTwoState -or $CycleTwoPayload.status -ne "ok") {
        Write-SmokeLog
        throw "Second packaged cycle did not become ready."
    }
    if (
        [int]$CycleTwoState.pid -eq [int]$RuntimeState.pid -or
        [string]$CycleTwoState.instance_token -ceq $PreviousRuntimeToken
    ) {
        throw "Second packaged cycle reused the previous owner identity."
    }
    Assert-NoOwnerChildren -Owner $Process
    $CycleTwoConfigUrl = "http://127.0.0.1:$([int]$CycleTwoState.port)/api/config"
    $CycleTwoSetupResponse = Invoke-SmokeHttpRequest `
        -Url $CycleTwoConfigUrl `
        -Method "POST" `
        -JsonBody $SetupJson
    if ($CycleTwoSetupResponse.StatusCode -ne 200) {
        Write-SmokeLog
        throw "Second packaged cycle setup write failed."
    }
    Request-GracefulQuit `
        -Owner $Process `
        -RuntimePort ([int]$CycleTwoState.port) `
        -CycleName "Second packaged cycle"
    $Process = $null

    # Preserve the existing stale-record recovery coverage without killing a
    # process: restore the first cycle's authenticated record after its clean
    # shutdown, then require the next owner to replace it.
    [System.IO.File]::WriteAllText(
        $RuntimeStateFile,
        $StaleRuntimeJson,
        [System.Text.UTF8Encoding]::new($false)
    )
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
    $StaleRuntimeRecovered = $false
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
        if (Test-Path -LiteralPath $RuntimeStateFile) {
            try {
                $RecoveryRuntimeState = Get-Content -LiteralPath $RuntimeStateFile -Raw | ConvertFrom-Json
                if (
                    [int]$RecoveryRuntimeState.pid -eq $Process.Id -and
                    [string]$RecoveryRuntimeState.instance_token -cne $PreviousRuntimeToken
                ) {
                    $StaleRuntimeRecovered = $true
                }
            } catch {
                $StaleRuntimeRecovered = $false
            }
        }
        if (
            $FailureContractObserved -and
            $RecoveryWindowObserved -and
            $StaleRuntimeRecovered
        ) {
            break
        }
        Start-Sleep -Milliseconds 250
    }
    if (-not $FailureContractObserved) {
        Write-SmokeLog
        throw "Injected startup failure did not produce the expected launcher phase and recovery log contract."
    }
    if (-not $StaleRuntimeRecovered) {
        Write-SmokeLog
        throw "A crash-leftover runtime record was not replaced by the next owner."
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

    Write-Host "DOCSight Desktop smoke passed: single ownership, packaged routes, two graceful open/write/quit cycles, listener and runtime cleanup, data reopen, and stale-state recovery are valid."
} catch {
    Write-SmokeLog
    throw
} finally {
    $CleanupProcesses = @(
        $Process,
        $LaunchOne,
        $LaunchTwo,
        $FollowerProcess,
        $ThirdProcess,
        $CycleTwoProcess
    ) | Where-Object { $null -ne $_ } | Sort-Object Id -Unique
    foreach ($CleanupProcess in $CleanupProcesses) {
        $CleanupProcess.Refresh()
        if (-not $CleanupProcess.HasExited) {
            Stop-Process -Id $CleanupProcess.Id -Force -ErrorAction SilentlyContinue
            $CleanupProcess.WaitForExit(10000) | Out-Null
        }
    }
    if ($null -ne $ForeignListener) {
        $ForeignListener.Stop()
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
    $env:DOCSIGHT_SMOKE_QUIT_SENTINEL = $PreviousSmokeQuitSentinel

    if (Test-Path $SmokeRoot) {
        Remove-Item -Recurse -Force $SmokeRoot -ErrorAction SilentlyContinue
    }
}
