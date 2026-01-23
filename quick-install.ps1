# Quick Install Script for Microsoft LISA on Windows
# This script installs upstream LISA from https://github.com/microsoft/lisa

[CmdletBinding()]
param (
    [switch]$SkipPython,
    [string]$PythonVersion = "3.12",
    [string]$InstallPath = "$env:USERPROFILE\lisa",
    [string]$Branch = "main"
)

$ErrorActionPreference = "Stop"

Write-Host "===== Microsoft LISA Quick Installation Script =====" -ForegroundColor Cyan
Write-Host "Installing from: https://github.com/microsoft/lisa" -ForegroundColor Cyan

# Function to update PATH
Function Update-PATH {
    $Env:PATH = (@($Env:PATH -split ';') + @([Environment]::GetEnvironmentVariable('PATH', 'Machine') -split ';') + @([Environment]::GetEnvironmentVariable('PATH', 'User') -split ';') | Select-Object -Unique) -join ';'
}

# Step 1: Check Python
if (-not $SkipPython) {
    Write-Host "`n[1/4] Checking Python..." -ForegroundColor Yellow
    
    # Check if Python is actually installed (not just the Windows Store alias)
    $pythonInstalled = $false
    $Python = Get-Command python -ErrorAction SilentlyContinue
    if ($Python) {
        # Try to run python --version to verify it's a real Python installation
        # Windows has an App Execution Alias that redirects to Microsoft Store
        try {
            $versionOutput = & python --version 2>&1
            if ($versionOutput -match 'Python \d+\.\d+') {
                $pythonInstalled = $true
                $version = $versionOutput
            }
        }
        catch {
            # Python command exists but failed - likely the Store alias
            $pythonInstalled = $false
        }
    }
    
    if ($pythonInstalled) {
        Write-Host "  [OK] Python is installed: $version" -ForegroundColor Green
        
        # Check if installed version matches requested version
        if ($version -match 'Python (\d+\.\d+)') {
            $installedMajorMinor = $Matches[1]
            if ($installedMajorMinor -ne $PythonVersion) {
                Write-Host "  [INFO] Installed Python ($installedMajorMinor) differs from requested ($PythonVersion)" -ForegroundColor Yellow
                Write-Host "  Attempting to install Python $PythonVersion..." -ForegroundColor Yellow
                $pythonInstalled = $false  # Trigger installation of requested version
            }
        }
    }

    if ($pythonInstalled) {
        # Check if version is 3.11 or higher (recommended)
        if ($version -match 'Python 3\.(\d+)') {
            $minorVersion = [int]$Matches[1]
            if ($minorVersion -lt 8) {
                Write-Host "  [ERROR] Python 3.8+ is required. Current: $version" -ForegroundColor Red
                Write-Host "  Please install Python 3.11+ from: https://www.python.org/downloads/" -ForegroundColor Cyan
                exit 1
            }
            elseif ($minorVersion -lt 11) {
                Write-Host "  [WARN] Python 3.11+ is recommended for best compatibility. Current: $version" -ForegroundColor Yellow
                Write-Host "  Consider upgrading from: https://www.python.org/downloads/" -ForegroundColor Cyan
            }
        }
    }
    else {
        Write-Host "  Python not found. Attempting to install Python $PythonVersion..." -ForegroundColor Yellow
        
        # Try winget first (available on Windows 10/11)
        $wingetCmd = Get-Command winget -ErrorAction SilentlyContinue
        if ($wingetCmd) {
            Write-Host "  Installing Python $PythonVersion via winget..." -ForegroundColor Yellow
            & winget install "Python.Python.$PythonVersion" --silent --accept-package-agreements --accept-source-agreements

            # Refresh PATH
            Update-PATH
            $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
            
            # Verify installation
            $Python = Get-Command python -ErrorAction SilentlyContinue
            if ($Python) {
                $version = & python --version 2>&1
                Write-Host "  [OK] Python installed: $version" -ForegroundColor Green
            }
            else {
                Write-Host "  [WARN] Python installed but not in PATH. Please restart your terminal." -ForegroundColor Yellow
                Write-Host "  Or manually add Python to PATH and re-run this script." -ForegroundColor Yellow
                exit 1
            }
        }
        else {
            # Fallback: Download and install Python directly
            Write-Host "  winget not found. Fetching latest Python $PythonVersion.x version..." -ForegroundColor Yellow

            # Dynamically fetch the latest version from python.org based on $PythonVersion
            $pythonFullVersion = "$PythonVersion.0"  # Default fallback version
            try {
                $releasesPage = Invoke-WebRequest -Uri "https://www.python.org/downloads/" -UseBasicParsing -TimeoutSec 10
                # Look for the latest version matching $PythonVersion.x in the downloads page
                $versionPattern = "Python ($([regex]::Escape($PythonVersion))\.\d+)"
                if ($releasesPage.Content -match $versionPattern) {
                    $pythonFullVersion = $Matches[1]
                    Write-Host "  Found latest Python $PythonVersion.x version: $pythonFullVersion" -ForegroundColor Gray
                }
            }
            catch {
                Write-Host "  Could not fetch latest version, using default: $pythonFullVersion" -ForegroundColor Gray
            }
            
            $pythonUrl = "https://www.python.org/ftp/python/$pythonFullVersion/python-$pythonFullVersion-amd64.exe"
            $installerPath = "$env:TEMP\python-$pythonFullVersion-amd64.exe"
            
            try {
                Write-Host "  Downloading from: $pythonUrl" -ForegroundColor Gray
                Invoke-WebRequest -Uri $pythonUrl -OutFile $installerPath -UseBasicParsing
                
                Write-Host "  Installing Python $PythonVersion (this may take a few minutes)..." -ForegroundColor Yellow
                $installArgs = "/quiet InstallAllUsers=1 PrependPath=1 Include_test=0"
                Start-Process -FilePath $installerPath -ArgumentList $installArgs -Wait -NoNewWindow
                
                # Clean up installer
                Remove-Item -Path $installerPath -Force -ErrorAction SilentlyContinue
                
                # Refresh PATH
                Update-PATH
                $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
                
                # Verify installation
                $Python = Get-Command python -ErrorAction SilentlyContinue
                if ($Python) {
                    $version = & python --version 2>&1
                    Write-Host "  [OK] Python installed: $version" -ForegroundColor Green
                }
                else {
                    Write-Host "  [WARN] Python installed but not immediately available." -ForegroundColor Yellow
                    Write-Host "  Please close and reopen PowerShell, then re-run this script." -ForegroundColor Yellow
                    exit 1
                }
            }
            catch {
                Write-Host "  [ERROR] Failed to download or install Python: $_" -ForegroundColor Red
                Write-Host "`n  Please install Python manually:" -ForegroundColor Yellow
                Write-Host "  1. Download Python $PythonVersion from: https://www.python.org/downloads/" -ForegroundColor Cyan
                Write-Host "  2. During installation, check 'Add Python to PATH'" -ForegroundColor Cyan
                Write-Host "  3. Re-run this script after installation" -ForegroundColor Cyan
                exit 1
            }
        }
    }
}
else {
    Write-Host "`n[1/4] Skipping Python check" -ForegroundColor Gray
}

# Step 2: Install Python dependencies
Write-Host "`n[2/4] Installing Python dependencies..." -ForegroundColor Yellow

try {
    & python -m pip install --upgrade pip --quiet
    Write-Host "  [OK] pip upgraded" -ForegroundColor Green
}
catch {
    Write-Host "  [WARN] pip upgrade failed, continuing..." -ForegroundColor Yellow
}

Write-Host "  Installing nox, toml, wheel..." -ForegroundColor Yellow
# Use --no-warn-script-location to suppress PATH warnings
& pip install --user --upgrade --no-warn-script-location nox toml wheel | Out-Null
Write-Host "  [OK] Dependencies installed" -ForegroundColor Green

# After installation, add Python Scripts directory to PATH
$sitePathDirectory = (Join-Path -Path (Split-Path -Path (python -m site --user-site) -Parent) -ChildPath Scripts)
if (Test-Path $sitePathDirectory) {
    # Add to current session PATH immediately
    if ($env:Path -notlike "*$sitePathDirectory*") {
        $env:Path = "$sitePathDirectory;$env:Path"
        Write-Host "  [INFO] Added to current session PATH: $sitePathDirectory" -ForegroundColor Gray
    }
    
    # Add to User PATH permanently
    $currentUserPath = [Environment]::GetEnvironmentVariable('PATH', 'User')
    if ($currentUserPath -notlike "*$sitePathDirectory*") {
        try {
            $newPath = if ($currentUserPath) { "$currentUserPath;$sitePathDirectory" } else { $sitePathDirectory }
            [Environment]::SetEnvironmentVariable('PATH', $newPath, 'User')
            Write-Host "  [OK] Added to User PATH permanently: $sitePathDirectory" -ForegroundColor Green
            Write-Host "  [INFO] PATH will be fully available in new terminal sessions" -ForegroundColor Gray
        }
        catch {
            Write-Host "  [WARN] Failed to update User PATH permanently" -ForegroundColor Yellow
            Write-Host "  Add this to your PATH manually: $sitePathDirectory" -ForegroundColor Yellow
        }
    }
}

# Step 3: Check Git
Write-Host "`n[3/4] Checking Git..." -ForegroundColor Yellow
$gitCmd = Get-Command git -ErrorAction SilentlyContinue
if ($gitCmd) {
    $gitVersion = & git --version 2>&1
    Write-Host "  [OK] Git is installed: $gitVersion" -ForegroundColor Green
}
else {
    Write-Host "  Git not found. Attempting to install Git..." -ForegroundColor Yellow
    
    # Try winget first
    $wingetCmd = Get-Command winget -ErrorAction SilentlyContinue
    if ($wingetCmd) {
        Write-Host "  Installing Git via winget..." -ForegroundColor Yellow
        & winget install Git.Git --silent --accept-package-agreements --accept-source-agreements
        
        # Refresh PATH
        Update-PATH
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
        
        # Verify installation
        $gitCmd = Get-Command git -ErrorAction SilentlyContinue
        if ($gitCmd) {
            $gitVersion = & git --version 2>&1
            Write-Host "  [OK] Git installed: $gitVersion" -ForegroundColor Green
        }
        else {
            Write-Host "  [WARN] Git installed but not in PATH. Please restart your terminal." -ForegroundColor Yellow
            Write-Host "  Or manually add Git to PATH and re-run this script." -ForegroundColor Yellow
            exit 1
        }
    }
    else {
        # Fallback: Download and install Git directly
        Write-Host "  winget not found. Fetching latest Git version..." -ForegroundColor Yellow

        # Dynamically fetch the latest Git version from GitHub API
        $gitVersion = "2.47.1"  # Default fallback version
        try {
            $releaseInfo = Invoke-RestMethod -Uri "https://api.github.com/repos/git-for-windows/git/releases/latest" -TimeoutSec 10
            # Tag name is like "v2.47.1.windows.1", extract version number
            if ($releaseInfo.tag_name -match 'v(\d+\.\d+\.\d+)') {
                $gitVersion = $Matches[1]
                Write-Host "  Found latest Git version: $gitVersion" -ForegroundColor Gray
            }
        }
        catch {
            Write-Host "  Could not fetch latest version, using default: $gitVersion" -ForegroundColor Gray
        }

        $gitUrl = "https://github.com/git-for-windows/git/releases/download/v$gitVersion.windows.1/Git-$gitVersion-64-bit.exe"
        $installerPath = "$env:TEMP\Git-$gitVersion-installer.exe"

        try {
            Write-Host "  Downloading from: $gitUrl" -ForegroundColor Gray
            Invoke-WebRequest -Uri $gitUrl -OutFile $installerPath -UseBasicParsing

            Write-Host "  Installing Git (this may take a few minutes)..." -ForegroundColor Yellow
            $installArgs = "/VERYSILENT /NORESTART /NOCANCEL /SP- /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS /COMPONENTS=`"icons,ext\reg\shellhere,assoc,assoc_sh`""
            Start-Process -FilePath $installerPath -ArgumentList $installArgs -Wait -NoNewWindow

            # Clean up installer
            Remove-Item -Path $installerPath -Force -ErrorAction SilentlyContinue

            # Refresh PATH
            Update-PATH
            $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")

            # Verify installation
            $gitCmd = Get-Command git -ErrorAction SilentlyContinue
            if ($gitCmd) {
                $gitVersion = & git --version 2>&1
                Write-Host "  [OK] Git installed: $gitVersion" -ForegroundColor Green
            }
            else {
                Write-Host "  [WARN] Git installed but not immediately available." -ForegroundColor Yellow
                Write-Host "  Please close and reopen PowerShell, then re-run this script." -ForegroundColor Yellow
                exit 1
            }
        }
        catch {
            Write-Host "  [ERROR] Failed to download or install Git: $_" -ForegroundColor Red
            Write-Host "`n  Please install Git manually:" -ForegroundColor Yellow
            Write-Host "  1. Download Git from: https://git-scm.com/download/win" -ForegroundColor Cyan
            Write-Host "  2. Re-run this script after installation" -ForegroundColor Cyan
            exit 1
        }
    }
}

# Step 4: Clone and install LISA
Write-Host "`n[4/4] Installing LISA from GitHub..." -ForegroundColor Yellow
$needsClone = $true

if (Test-Path $InstallPath) {
    Write-Host "  Directory $InstallPath already exists" -ForegroundColor Yellow
    
    # Validate existing directory structure
    $existingValid = Test-Path "$InstallPath\pyproject.toml"
    if ($existingValid) {
        Write-Host "  [OK] Existing directory appears to be a valid LISA repository" -ForegroundColor Green
    }
    else {
        Write-Host "  [WARN] Existing directory is incomplete or corrupted (pyproject.toml not found)" -ForegroundColor Yellow
    }
    
    $response = Read-Host "  Do you want to remove it and re-clone? (y/N)"
    if ($response -eq 'y' -or $response -eq 'Y') {
        Remove-Item -Path $InstallPath -Recurse -Force
        Write-Host "  Cloning LISA repository..." -ForegroundColor Yellow
        # Temporarily allow errors for git clone (it outputs to stderr)
        $prevErrorPref = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        & git clone --branch $Branch https://github.com/microsoft/lisa.git $InstallPath 2>&1 | Out-Null
        $ErrorActionPreference = $prevErrorPref
    }
    else {
        if (-not $existingValid) {
            Write-Host "  [ERROR] Cannot use existing directory - it is incomplete or corrupted" -ForegroundColor Red
            Write-Host "  Please remove the directory manually and re-run the script:" -ForegroundColor Yellow
            Write-Host "  Remove-Item -Path '$InstallPath' -Recurse -Force" -ForegroundColor Cyan
            exit 1
        }
        Write-Host "  Using existing directory..." -ForegroundColor Yellow
        $needsClone = $false
    }
}

if ($needsClone -and -not (Test-Path $InstallPath)) {
    Write-Host "  Cloning LISA repository to $InstallPath..." -ForegroundColor Yellow
    # Temporarily allow errors for git clone (it outputs to stderr)
    $prevErrorPref = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & git clone --branch $Branch https://github.com/microsoft/lisa.git $InstallPath 2>&1 | Out-Null
    $ErrorActionPreference = $prevErrorPref
}

# Verify clone was successful
if (-not (Test-Path "$InstallPath\pyproject.toml")) {
    Write-Host "  [ERROR] LISA repository clone failed or incomplete" -ForegroundColor Red
    Write-Host "  Expected file not found: $InstallPath\pyproject.toml" -ForegroundColor Red
    exit 1
}

try {
    Push-Location $InstallPath
    Write-Host "  Installing LISA with Azure extensions in editable mode..." -ForegroundColor Yellow
    & python -m pip install --editable .[azure] --config-settings editable_mode=compat --quiet
    Pop-Location
    
    Write-Host "  [OK] LISA installed from $InstallPath" -ForegroundColor Green
}
catch {
    Write-Host "  [ERROR] LISA installation failed: $_" -ForegroundColor Red
    Pop-Location -ErrorAction SilentlyContinue
    exit 1
}

# Verify installation
Write-Host "`n===== Verifying Installation =====" -ForegroundColor Cyan
$lisaCmd = Get-Command lisa -ErrorAction SilentlyContinue
if ($lisaCmd) {
    Write-Host "[OK] LISA executable found: $($lisaCmd.Source)" -ForegroundColor Green
    Write-Host "`nRunning 'lisa -h' to verify..." -ForegroundColor Yellow
    & lisa -h
    Write-Host "`n===== Installation Completed Successfully! =====" -ForegroundColor Green
    Write-Host "`nLISA installed to: $InstallPath" -ForegroundColor Cyan
    Write-Host "You can now run LISA with: lisa" -ForegroundColor Cyan
    Write-Host "For help, run: lisa --help" -ForegroundColor Cyan
    Write-Host "`n[NOTE] Optional packages (baremetal, aws, ai) can be installed separately if needed." -ForegroundColor Gray
    Write-Host "`nTo get started:" -ForegroundColor Yellow
    Write-Host "  1. Create a runbook file" -ForegroundColor White
    Write-Host "  2. Run: lisa -r <your-runbook.yml>" -ForegroundColor White
}
else {
    Write-Host "[ERROR] LISA executable not found in PATH" -ForegroundColor Red
    Write-Host "You may need to restart your terminal" -ForegroundColor Yellow
    exit 1
}
