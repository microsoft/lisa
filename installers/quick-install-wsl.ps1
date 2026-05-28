# Quick Install Script for Microsoft LISA inside WSL (from Windows host)
# This bootstraps WSL if missing, then runs quick-install.sh inside the chosen
# WSL distribution. Useful for Windows users who prefer the Linux toolchain.

[CmdletBinding()]
param (
    [string]$Distro = "Ubuntu",
    [string]$Branch = "main",
    [string]$InstallPath = "/home/`$USER/lisa",
    [switch]$SkipWslInstall
)

$ErrorActionPreference = "Stop"

Write-Host "===== Microsoft LISA Quick Install (WSL bootstrap) =====" -ForegroundColor Cyan
Write-Host "Target distro: $Distro" -ForegroundColor Cyan
Write-Host "LISA branch:   $Branch" -ForegroundColor Cyan

# Step 1: Verify wsl.exe is available
$wslCmd = Get-Command wsl.exe -ErrorAction SilentlyContinue
if (-not $wslCmd) {
    Write-Host "[ERROR] wsl.exe not found. Windows 10 (build 19041+) or Windows 11 is required." -ForegroundColor Red
    Write-Host "Enable WSL via Settings > Apps > Optional features, or run as Administrator:" -ForegroundColor Yellow
    Write-Host "    wsl --install" -ForegroundColor Yellow
    exit 1
}

# Step 2: Check whether the requested distro is already installed
$installedDistros = @()
try {
    # wsl --list -q emits UTF-16; pipe through Out-String to normalize
    $rawList = & wsl.exe --list --quiet 2>$null | Out-String
    $installedDistros = $rawList -split "`r?`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" }
}
catch {
    Write-Host "[WARN] Could not list installed WSL distributions: $_" -ForegroundColor Yellow
}

$distroInstalled = $installedDistros -contains $Distro

if (-not $distroInstalled) {
    if ($SkipWslInstall) {
        Write-Host "[ERROR] Distro '$Distro' is not installed and -SkipWslInstall was passed." -ForegroundColor Red
        Write-Host "Installed distros: $($installedDistros -join ', ')" -ForegroundColor Yellow
        exit 1
    }
    Write-Host "`n[1/2] Distro '$Distro' is not installed. Installing now..." -ForegroundColor Yellow
    Write-Host "      This requires Administrator privileges and a reboot may be needed." -ForegroundColor Yellow
    Write-Host "      Running: wsl --install -d $Distro --no-launch" -ForegroundColor Gray
    & wsl.exe --install -d $Distro --no-launch
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] 'wsl --install -d $Distro' failed (exit $LASTEXITCODE)." -ForegroundColor Red
        Write-Host "Run PowerShell as Administrator and retry, or install the distro manually from the Microsoft Store." -ForegroundColor Yellow
        exit 1
    }
    Write-Host "`n[ACTION REQUIRED] WSL has been provisioned." -ForegroundColor Cyan
    Write-Host "  1. Launch the '$Distro' app from the Start menu to create a UNIX user/password." -ForegroundColor Cyan
    Write-Host "  2. Re-run this script after the user is created." -ForegroundColor Cyan
    exit 0
}
else {
    Write-Host "`n[1/2] Distro '$Distro' is already installed." -ForegroundColor Green
}

# Step 3: Run quick-install.sh inside the distro
Write-Host "`n[2/2] Running LISA quick-install.sh inside '$Distro'..." -ForegroundColor Yellow

$scriptUrl = "https://raw.githubusercontent.com/microsoft/lisa/$Branch/installers/quick-install.sh"
# Pass the install path verbatim into bash; the literal $USER will be expanded
# inside the WSL shell, not in PowerShell.
$bashCmd = "set -e; curl -fsSL '$scriptUrl' -o /tmp/lisa-quick-install.sh && bash /tmp/lisa-quick-install.sh --install-path `"$InstallPath`" --branch '$Branch' --use-venv true"

& wsl.exe -d $Distro -- bash -c $bashCmd
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] LISA installation inside WSL failed (exit $LASTEXITCODE)." -ForegroundColor Red
    exit 1
}

Write-Host "`n===== Installation Completed =====" -ForegroundColor Green
Write-Host "Run LISA from PowerShell with:" -ForegroundColor Cyan
Write-Host "    wsl -d $Distro -- lisa --help" -ForegroundColor White
Write-Host "Or open a WSL shell and run 'lisa' directly." -ForegroundColor Cyan
