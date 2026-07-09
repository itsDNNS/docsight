[CmdletBinding()]
param(
    [string]$Version = "",
    [string]$PythonLauncher = "py",
    [string]$PythonVersion = "3.13",
    [string]$OutputDirectory = ""
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$BuildRoot = Join-Path $ScriptDir "build"
$DistRoot = Join-Path $ScriptDir "dist"
$VenvRoot = Join-Path $BuildRoot ".venv"
$VenvPython = Join-Path $VenvRoot "Scripts\python.exe"
$VersionFile = Join-Path $BuildRoot "VERSION"
$SpecFile = Join-Path $ScriptDir "docsight.spec"
$BundleDir = Join-Path $DistRoot "DOCSight"

if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = $DistRoot
}
if (-not [System.IO.Path]::IsPathRooted($OutputDirectory)) {
    $OutputDirectory = Join-Path (Get-Location) $OutputDirectory
}
$OutputDirectory = [System.IO.Path]::GetFullPath($OutputDirectory)

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(ValueFromRemainingArguments = $true)][string[]]$CommandArgs
    )

    & $FilePath @CommandArgs
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath failed with exit code $LASTEXITCODE"
    }
}

function Invoke-HostPython {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$PythonArgs)
    if ($PythonLauncher -eq "py" -and -not [string]::IsNullOrWhiteSpace($PythonVersion)) {
        & $PythonLauncher "-$PythonVersion" @PythonArgs
    } else {
        & $PythonLauncher @PythonArgs
    }
}

function Get-BuildVersion {
    if (-not [string]::IsNullOrWhiteSpace($Version)) {
        return $Version.Trim()
    }

    try {
        $gitVersion = (& git -C $RepoRoot describe --tags --always --dirty 2>$null).Trim()
        if (-not [string]::IsNullOrWhiteSpace($gitVersion)) {
            return $gitVersion
        }
    } catch {
        # Fall back below when git is unavailable, e.g. an unpacked source archive.
    }

    return "dev-$(Get-Date -Format 'yyyyMMddHHmmss')"
}

function ConvertTo-SafeFileName {
    param([string]$Value)
    return ($Value -replace '[^A-Za-z0-9._-]', '-')
}

$ResolvedVersion = Get-BuildVersion
$SafeVersion = ConvertTo-SafeFileName $ResolvedVersion

New-Item -ItemType Directory -Force -Path $BuildRoot, $DistRoot, $OutputDirectory | Out-Null
[System.IO.File]::WriteAllText($VersionFile, "$ResolvedVersion`n", [System.Text.UTF8Encoding]::new($false))

if (-not (Test-Path $VenvPython)) {
    Invoke-HostPython -m venv $VenvRoot
    if ($LASTEXITCODE -ne 0) {
        throw "$PythonLauncher failed to create venv with exit code $LASTEXITCODE"
    }
}

Invoke-Checked $VenvPython -m pip install --upgrade pip
Invoke-Checked $VenvPython -m pip install --require-hashes -r (Join-Path $ScriptDir "requirements-runtime-windows.txt")
Invoke-Checked $VenvPython -m pip install --require-hashes -r (Join-Path $ScriptDir "requirements-build.txt")

if (Test-Path $BundleDir) {
    Remove-Item -Recurse -Force $BundleDir
}

Invoke-Checked $VenvPython -m PyInstaller --noconfirm --clean --distpath $DistRoot --workpath (Join-Path $BuildRoot "pyinstaller") $SpecFile

$ZipPath = Join-Path $OutputDirectory "DOCSight-Desktop-Preview-win64-$SafeVersion.zip"
$HashPath = "$ZipPath.sha256"
if (Test-Path $ZipPath) {
    Remove-Item -Force $ZipPath
}
if (Test-Path $HashPath) {
    Remove-Item -Force $HashPath
}

Compress-Archive -Path $BundleDir -DestinationPath $ZipPath -Force
$Hash = (Get-FileHash -Algorithm SHA256 -Path $ZipPath).Hash.ToLowerInvariant()
$HashLine = "$Hash  $(Split-Path -Leaf $ZipPath)"
Set-Content -Path $HashPath -Value $HashLine -Encoding ASCII

Write-Host "DOCSight Desktop Preview bundle created: $ZipPath"
Write-Host "SHA256: $Hash"
