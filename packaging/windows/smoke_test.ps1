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
$Process = $null
$HttpHandler = $null
$HttpClient = $null
$LogFile = Join-Path $LocalAppData "DOCSight\logs\docsight.log"
$HealthUrl = "http://127.0.0.1:$Port/health"
$ReportUrl = "http://127.0.0.1:$Port/api/report"
$ConfigUrl = "http://127.0.0.1:$Port/api/config"

function Write-SmokeLog {
    if (Test-Path $LogFile) {
        Write-Host "--- DOCSight Desktop log ---"
        Get-Content -Path $LogFile -Tail 200 | ForEach-Object { Write-Host $_ }
        Write-Host "--- end DOCSight Desktop log ---"
    } else {
        Write-Host "DOCSight Desktop log not found: $LogFile"
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

    $env:LOCALAPPDATA = $LocalAppData
    $env:WEB_PORT = [string]$Port
    $env:DOCSIGHT_SKIP_BROWSER = "1"

    $HttpHandler = [System.Net.Http.HttpClientHandler]::new()
    $HttpHandler.UseProxy = $false
    $HttpClient = [System.Net.Http.HttpClient]::new($HttpHandler)
    $HttpClient.Timeout = [TimeSpan]::FromSeconds([Math]::Max(3, $TimeoutSeconds))

    $Process = Start-Process -FilePath $Executable -WorkingDirectory $LaunchBundleDir -PassThru -WindowStyle Hidden
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

    $Connections = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
    if (-not ($Connections | Where-Object { $_.LocalAddress -eq "127.0.0.1" })) {
        $Addresses = ($Connections | ForEach-Object { $_.LocalAddress } | Sort-Object -Unique) -join ", "
        Write-SmokeLog
        throw "DOCSight is not listening on 127.0.0.1:$Port. Observed listener addresses: $Addresses"
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

    if (-not (Test-Path $LogFile)) {
        throw "DOCSight Desktop log not found for post-smoke validation: $LogFile"
    }
    $LogText = Get-Content -Path $LogFile -Raw
    if ($LogText -match "Module 'docsight\.reports': failed to import routes") {
        Write-SmokeLog
        throw "DOCSight Desktop log contains a Reports route import failure."
    }
    if ($LogText -match "No module named ['`"]unittest['`"]") {
        Write-SmokeLog
        throw "DOCSight Desktop log contains a missing unittest import."
    }

    Write-Host "DOCSight Desktop smoke passed: copied package path supports spaces/non-ASCII, health/version and loopback listener are valid, Reports route is registered, and /api/report returned application/pdf beginning %PDF-."
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

    if (Test-Path $SmokeRoot) {
        Remove-Item -Recurse -Force $SmokeRoot -ErrorAction SilentlyContinue
    }
}
