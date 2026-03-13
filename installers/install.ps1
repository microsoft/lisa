# Install Script for Microsoft LISA on Windows
# Clones the LISA repository to the default path and installs it.
# Prerequisites: Python 3.8+ and Git must already be installed.
# For a fully automated setup (including Python/Git installation), use quick-install.ps1 instead.

[CmdletBinding()]
param (
    [string]$InstallPath = "$env:USERPROFILE\lisa",
    [string]$Branch = "main"
)

$ErrorActionPreference = "Stop"

Write-Host "===== Microsoft LISA Install Script =====" -ForegroundColor Cyan
Write-Host "Default installation path: $env:USERPROFILE\lisa" -ForegroundColor Cyan
Write-Host "Installing to: $InstallPath" -ForegroundColor Cyan

# Check Git is available
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] Git is not installed or not in PATH." -ForegroundColor Red
    Write-Host "Please install Git from https://git-scm.com/download/win and re-run this script." -ForegroundColor Yellow
    exit 1
}

# Check Python is available
$pythonExe = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonExe) {
    Write-Host "[ERROR] Python is not installed or not in PATH." -ForegroundColor Red
    Write-Host "Please install Python 3.8+ from https://www.python.org/downloads/ and re-run this script." -ForegroundColor Yellow
    exit 1
}

$pythonVersion = & python --version 2>&1
Write-Host "[OK] Found: $pythonVersion" -ForegroundColor Green

# Clone the LISA repository
Write-Host "`n[1/2] Cloning LISA repository..." -ForegroundColor Yellow

if (Test-Path $InstallPath) {
    Write-Host "  Directory $InstallPath already exists." -ForegroundColor Yellow
    if (Test-Path "$InstallPath\pyproject.toml") {
        Write-Host "  [OK] Existing LISA repository found at $InstallPath" -ForegroundColor Green
    }
    else {
        Write-Host "  [WARN] Directory exists but does not appear to be a valid LISA repository." -ForegroundColor Yellow
        $response = Read-Host "  Remove and re-clone? (y/N)"
        if ($response -eq 'y' -or $response -eq 'Y') {
            Remove-Item -Path $InstallPath -Recurse -Force
            Write-Host "  Cloning LISA repository to $InstallPath..." -ForegroundColor Yellow
            $prevErrorPref = $ErrorActionPreference
            $ErrorActionPreference = "Continue"
            & git clone --branch $Branch https://github.com/microsoft/lisa.git $InstallPath 2>&1 | Out-Null
            $ErrorActionPreference = $prevErrorPref
        }
        else {
            Write-Host "  [ERROR] Cannot use existing directory - pyproject.toml not found." -ForegroundColor Red
            Write-Host "  Remove it manually and re-run: Remove-Item -Path '$InstallPath' -Recurse -Force" -ForegroundColor Cyan
            exit 1
        }
    }
}
else {
    Write-Host "  Cloning LISA repository to $InstallPath..." -ForegroundColor Yellow
    $prevErrorPref = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & git clone --branch $Branch https://github.com/microsoft/lisa.git $InstallPath 2>&1 | Out-Null
    $ErrorActionPreference = $prevErrorPref
}

if (-not (Test-Path "$InstallPath\pyproject.toml")) {
    Write-Host "[ERROR] Clone failed - pyproject.toml not found at $InstallPath." -ForegroundColor Red
    exit 1
}

Write-Host "  [OK] LISA repository cloned to $InstallPath" -ForegroundColor Green

# Install LISA
Write-Host "`n[2/2] Installing LISA..." -ForegroundColor Yellow

try {
    Push-Location $InstallPath
    & python -m pip install --editable .[azure] --config-settings editable_mode=compat --quiet
    Pop-Location
    Write-Host "  [OK] LISA installed from $InstallPath" -ForegroundColor Green
}
catch {
    Write-Host "  [ERROR] LISA installation failed: $_" -ForegroundColor Red
    Pop-Location -ErrorAction SilentlyContinue
    exit 1
}

Write-Host "`n===== Installation Complete =====" -ForegroundColor Green
Write-Host "LISA installed to: $InstallPath" -ForegroundColor Cyan
Write-Host "Run 'lisa --help' to get started." -ForegroundColor Cyan
