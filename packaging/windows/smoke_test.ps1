[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$BundleDir,
    [Parameter(Mandatory = $true)][string]$ExpectedVersion,
    [int]$Port = 8765,
    [int]$TimeoutSeconds = 60
)

$ErrorActionPreference = "Stop"

$BundleDir = [System.IO.Path]::GetFullPath($BundleDir)
$Executable = Join-Path $BundleDir "DOCSight.exe"
if (-not (Test-Path $Executable)) {
    throw "DOCSight executable not found: $Executable"
}

$SmokeRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("docsight-desktop-smoke-" + [guid]::NewGuid().ToString("N"))
$LocalAppData = Join-Path $SmokeRoot "LocalAppData"
New-Item -ItemType Directory -Force -Path $LocalAppData | Out-Null

$PreviousLocalAppData = $env:LOCALAPPDATA
$PreviousWebPort = $env:WEB_PORT
$PreviousSkipBrowser = $env:DOCSIGHT_SKIP_BROWSER
$Process = $null
$LogFile = Join-Path $LocalAppData "DOCSight\logs\docsight.log"
$HealthUrl = "http://127.0.0.1:$Port/health"

function Write-SmokeLog {
    if (Test-Path $LogFile) {
        Write-Host "--- DOCSight Desktop log ---"
        Get-Content -Path $LogFile -Tail 200 | ForEach-Object { Write-Host $_ }
        Write-Host "--- end DOCSight Desktop log ---"
    } else {
        Write-Host "DOCSight Desktop log not found: $LogFile"
    }
}

try {
    $env:LOCALAPPDATA = $LocalAppData
    $env:WEB_PORT = [string]$Port
    $env:DOCSIGHT_SKIP_BROWSER = "1"

    $Process = Start-Process -FilePath $Executable -PassThru -WindowStyle Hidden
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

    Write-Host "DOCSight Desktop smoke passed: $HealthUrl returned status=ok version=$($Payload.version), listener=127.0.0.1:$Port"
} finally {
    if ($null -ne $Process -and -not $Process.HasExited) {
        Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
        $Process.WaitForExit(10000) | Out-Null
    }

    $env:LOCALAPPDATA = $PreviousLocalAppData
    $env:WEB_PORT = $PreviousWebPort
    $env:DOCSIGHT_SKIP_BROWSER = $PreviousSkipBrowser

    if (Test-Path $SmokeRoot) {
        Remove-Item -Recurse -Force $SmokeRoot -ErrorAction SilentlyContinue
    }
}
