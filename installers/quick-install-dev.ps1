# Quick Install Script for Microsoft LISA dev environment on Windows
# Sets up a Windows-native editable install in a .venv so you can F5-debug
# LISA in VS Code without WSL.
#
# Steps:
#   1. Verify (or install) a supported Python on Windows.
#   2. Clone (or reuse) the LISA repo.
#   3. Create .venv and pip install -e .[azure,libvirt] (libvirt is optional).
#   4. Drop a .vscode/launch.json with a "Python: lisa" debug configuration.
#
# Usage:
#   .\quick-install-dev.ps1
#   .\quick-install-dev.ps1 -InstallPath C:\code\lisa -Branch main
#   .\quick-install-dev.ps1 -NoClone   # use existing checkout at -InstallPath
#   .\quick-install-dev.ps1 -SkipLibvirt  # skip [libvirt] extra (avoids native build)

[CmdletBinding()]
param (
    [string]$InstallPath = "$env:USERPROFILE\lisa",
    [string]$Branch = "main",
    [string]$PythonVersion = "3.12",
    [switch]$NoClone,
    [switch]$SkipLibvirt,
    [switch]$SkipLaunchJson
)

$ErrorActionPreference = "Stop"

Write-Host "===== Microsoft LISA Quick Install (Windows dev) =====" -ForegroundColor Cyan
Write-Host "Install path : $InstallPath" -ForegroundColor Cyan
Write-Host "Branch       : $Branch"      -ForegroundColor Cyan
Write-Host "Python target: $PythonVersion" -ForegroundColor Cyan

function Get-PythonExe {
    param([string]$Version)
    # Prefer py launcher
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) {
        try {
            $p = & py.exe -$Version -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $p) { return $p.Trim() }
        } catch { }
    }
    # Fallback: any python on PATH that satisfies the version
    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($python) {
        $v = & python.exe -c "import sys; print('{}.{}'.format(*sys.version_info[:2]))" 2>$null
        if ($LASTEXITCODE -eq 0 -and $v -and ([version]$v -ge [version]"3.8")) {
            return (& python.exe -c "import sys; print(sys.executable)").Trim()
        }
    }
    return $null
}

# ---- Step 1: Python ----------------------------------------------------------
Write-Host "`n[1/4] Locating Python $PythonVersion..." -ForegroundColor Yellow
$pythonExe = Get-PythonExe -Version $PythonVersion
if (-not $pythonExe) {
    Write-Host "      Not found. Attempting install via winget..." -ForegroundColor Yellow
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if (-not $winget) {
        Write-Host "[ERROR] winget not available. Install Python $PythonVersion manually from python.org and re-run." -ForegroundColor Red
        exit 1
    }
    $pkgId = "Python.Python." + $PythonVersion
    & winget.exe install -e --id $pkgId --accept-package-agreements --accept-source-agreements --silent
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] winget install $pkgId failed (exit $LASTEXITCODE)." -ForegroundColor Red
        exit 1
    }
    # Refresh PATH for current session
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + `
                [System.Environment]::GetEnvironmentVariable("Path", "User")
    $pythonExe = Get-PythonExe -Version $PythonVersion
    if (-not $pythonExe) {
        Write-Host "[ERROR] Python $PythonVersion still not found after install. Open a new shell and re-run." -ForegroundColor Red
        exit 1
    }
}
Write-Host "      Using: $pythonExe" -ForegroundColor Green

# ---- Step 2: Clone -----------------------------------------------------------
Write-Host "`n[2/4] Preparing repository at $InstallPath..." -ForegroundColor Yellow
if ($NoClone) {
    if (-not (Test-Path (Join-Path $InstallPath "pyproject.toml"))) {
        Write-Host "[ERROR] -NoClone set but no pyproject.toml at $InstallPath" -ForegroundColor Red
        exit 1
    }
    Write-Host "      Reusing existing checkout." -ForegroundColor Green
}
else {
    if (-not (Get-Command git.exe -ErrorAction SilentlyContinue)) {
        Write-Host "[ERROR] git.exe not on PATH. Install Git for Windows and re-run." -ForegroundColor Red
        exit 1
    }
    if (Test-Path $InstallPath) {
        if (Test-Path (Join-Path $InstallPath ".git")) {
            Write-Host "      Existing repo detected, fetching and checking out $Branch..." -ForegroundColor Gray
            Push-Location $InstallPath
            try {
                & git.exe fetch origin $Branch --quiet
                & git.exe checkout $Branch --quiet
                & git.exe pull --ff-only origin $Branch --quiet
            } finally { Pop-Location }
        } else {
            Write-Host "[ERROR] $InstallPath exists but is not a git repo. Remove it or pass -NoClone." -ForegroundColor Red
            exit 1
        }
    } else {
        Write-Host "      Cloning microsoft/lisa@$Branch..." -ForegroundColor Gray
        & git.exe clone --branch $Branch https://github.com/microsoft/lisa.git $InstallPath --quiet
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[ERROR] git clone failed (exit $LASTEXITCODE)." -ForegroundColor Red
            exit 1
        }
    }
}

# ---- Step 3: venv + editable install ----------------------------------------
Write-Host "`n[3/4] Creating .venv and installing LISA (editable)..." -ForegroundColor Yellow
Push-Location $InstallPath
try {
    $venvPath = Join-Path $InstallPath ".venv"
    if (-not (Test-Path $venvPath)) {
        & $pythonExe -m venv .venv
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[ERROR] Failed to create .venv" -ForegroundColor Red
            exit 1
        }
    } else {
        Write-Host "      Reusing existing .venv" -ForegroundColor Gray
    }

    $venvPython = Join-Path $venvPath "Scripts\python.exe"
    if (-not (Test-Path $venvPython)) {
        Write-Host "[ERROR] venv python not found at $venvPython" -ForegroundColor Red
        exit 1
    }

    & $venvPython -m pip install --upgrade pip setuptools wheel
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] pip upgrade failed" -ForegroundColor Red
        exit 1
    }

    $extras = if ($SkipLibvirt) { "azure" } else { "azure,libvirt" }
    Write-Host "      pip install -e .[$extras]" -ForegroundColor Gray
    & $venvPython -m pip install --editable ".[$extras]" --config-settings editable_mode=compat
    if ($LASTEXITCODE -ne 0) {
        if (-not $SkipLibvirt) {
            Write-Host "[WARN] Editable install with [libvirt] failed. Retrying with [azure] only..." -ForegroundColor Yellow
            & $venvPython -m pip install --editable ".[azure]" --config-settings editable_mode=compat
            if ($LASTEXITCODE -ne 0) {
                Write-Host "[ERROR] Editable install failed." -ForegroundColor Red
                exit 1
            }
        } else {
            Write-Host "[ERROR] Editable install failed." -ForegroundColor Red
            exit 1
        }
    }
} finally {
    Pop-Location
}

# ---- Step 4: VS Code launch.json --------------------------------------------
Write-Host "`n[4/4] Writing VS Code debug configuration..." -ForegroundColor Yellow
if ($SkipLaunchJson) {
    Write-Host "      Skipped (-SkipLaunchJson)" -ForegroundColor Gray
}
else {
    $vscodeDir = Join-Path $InstallPath ".vscode"
    if (-not (Test-Path $vscodeDir)) { New-Item -ItemType Directory -Path $vscodeDir | Out-Null }
    $launchPath = Join-Path $vscodeDir "launch.json"

    $venvPythonForJson = (Join-Path $InstallPath ".venv\Scripts\python.exe") -replace '\\', '\\'
    $cwdForJson        = $InstallPath -replace '\\', '\\'

    # settings.json — pins the workspace interpreter so the Python extension
    # picks up the venv (newer ms-python ignores launch.json's "python" field).
    $settingsPath = Join-Path $vscodeDir "settings.json"
    $settingsJson = @"
{
    "python.defaultInterpreterPath": "${venvPythonForJson}",
    "python.terminal.activateEnvironment": true
}
"@
    if (Test-Path $settingsPath) {
        Copy-Item $settingsPath "$settingsPath.bak" -Force
        Write-Host "      Existing settings.json backed up to $settingsPath.bak" -ForegroundColor Gray
    }
    Set-Content -Path $settingsPath -Value $settingsJson -Encoding UTF8
    Write-Host "      Wrote $settingsPath" -ForegroundColor Green

    $launchJson = @"
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Python: lisa (module)",
            "type": "debugpy",
            "request": "launch",
            "module": "lisa",
            "cwd": "`${workspaceFolder}",
            "python": "`${command:python.interpreterPath}",
            "console": "integratedTerminal",
            "justMyCode": false,
            "args": [
                "-r",
                "lisa/examples/runbook/hello_world.yml",
                "-d"
            ]
        },
        {
            "name": "Python: Current File",
            "type": "debugpy",
            "request": "launch",
            "program": "`${file}",
            "python": "`${command:python.interpreterPath}",
            "console": "integratedTerminal",
            "justMyCode": false
        }
    ]
}
"@

    if (Test-Path $launchPath) {
        $backup = "$launchPath.bak"
        Copy-Item $launchPath $backup -Force
        Write-Host "      Existing launch.json backed up to $backup" -ForegroundColor Gray
    }
    Set-Content -Path $launchPath -Value $launchJson -Encoding UTF8
    Write-Host "      Wrote $launchPath" -ForegroundColor Green
}

Write-Host "`n===== Dev environment ready =====" -ForegroundColor Green
Write-Host "Open the project in VS Code:" -ForegroundColor Cyan
Write-Host "    code `"$InstallPath`"" -ForegroundColor White
Write-Host "Activate the venv from a shell:" -ForegroundColor Cyan
Write-Host "    & `"$InstallPath\.venv\Scripts\Activate.ps1`"" -ForegroundColor White
Write-Host "Run LISA:" -ForegroundColor Cyan
Write-Host "    & `"$InstallPath\.venv\Scripts\python.exe`" -m lisa --help" -ForegroundColor White
Write-Host "Debug in VS Code:" -ForegroundColor Cyan
Write-Host "    Press F5 and pick 'Python: lisa (module)'." -ForegroundColor White
