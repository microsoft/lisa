# Quick Container Script for LISA on Windows
# Installs Docker CE (not Docker Desktop), pulls LISA image, and runs LISA in a Windows container.
# Run as Administrator.

[CmdletBinding()]
param (
    [string]$Runbook,
    [switch]$Interactive,
    [string[]]$Variable,
    [string]$MountPath,
    [string]$LogPath = ".\lisa-logs",
    [string]$ContainerName = "lisa-runner",
    [switch]$Keep,
    [string]$SubscriptionId,
    [string]$Token,
    [string]$Image = "mcr.microsoft.com/lisa/runtime:latest",
    [switch]$Pull,
    [string]$ExtraArgs,
    [switch]$InstallDocker,
    [switch]$InternalRunbook,
    [ValidateSet("process", "hyperv")]
    [string]$Isolation = "process",
    [ValidateSet("nat", "transparent")]
    [string]$Network = "transparent",
    [switch]$Help
)

$ErrorActionPreference = "Stop"

# ── Helper functions ──────────────────────────────────────────────────

function Write-Info    { param([string]$Msg) Write-Host "[INFO] $Msg" -ForegroundColor Green }
function Write-Warn    { param([string]$Msg) Write-Host "[WARNING] $Msg" -ForegroundColor Yellow }
function Write-Err     { param([string]$Msg) Write-Host "[ERROR] $Msg" -ForegroundColor Red }

function Show-Help {
    @"

Quick Container Script for LISA on Windows
Usage: .\quick-container.ps1 [OPTIONS]

OPTIONS:
    -Runbook PATH               Path to runbook file or container internal path
                                  External file: .\my-runbook.yml (will be mounted)
                                  Internal path: lisa/microsoft/runbook/azure.yml
    -Interactive                Start an interactive PowerShell in the container
    -Variable KEY:VALUE         LISA variable (can be specified multiple times)
                                  Example: -Variable subscription_id:xxx,location:westus2
    -MountPath PATH             Mount a local directory into the container at C:\workspace
    -LogPath PATH               Local directory to save LISA logs (default: .\lisa-logs)
    -ContainerName NAME         Container name (default: lisa-runner)
    -Keep                       Keep container after exit (don't auto-remove)
    -SubscriptionId ID          Azure subscription ID
    -Token TOKEN                Azure access token
    -Image IMAGE                Docker image (default: mcr.microsoft.com/lisa/runtime:latest)
    -Pull                       Force pull latest image
    -ExtraArgs ARGS             Extra arguments passed to docker run
    -InstallDocker              Install Docker CE if not present
    -InternalRunbook            Force treat runbook as container internal path (no mount)
    -Help                       Show this help message

EXAMPLES:
    # Install Docker CE and run interactive container
    .\quick-container.ps1 -InstallDocker -Interactive

    # Run with container internal runbook
    .\quick-container.ps1 -Runbook lisa/microsoft/runbook/azure.yml `
        -SubscriptionId xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

    # Run with Azure token authentication
    `$token = az account get-access-token --query accessToken -o tsv
    .\quick-container.ps1 -Runbook lisa/microsoft/runbook/azure.yml `
        -SubscriptionId xxx -Token `$token

    # Start an interactive shell
    .\quick-container.ps1 -Interactive

    # Run with external runbook file
    .\quick-container.ps1 -Runbook .\runbook.yml

    # Mount a local directory to override container files
    # NOTE: Windows containers only support mounting directories, not
    #       individual files. Mount the parent directory instead.
    .\quick-container.ps1 -Runbook lisa/microsoft/runbook/azure.yml `
        -SubscriptionId xxx -Token `$token `
        -ExtraArgs "-v C:\my\local\lisa\util:C:\app\lisa\lisa\util"

PREREQUISITES:
    - Windows 10/11 Pro/Enterprise or Windows Server 2019+
    - Containers Windows feature enabled
    - Docker CE installed (use -InstallDocker to install automatically)
    - Run this script as Administrator for Docker installation / permission fixes

"@
}

# ── Check administrator privileges ───────────────────────────────────

function Test-Administrator {
    $currentUser = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($currentUser)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# ── Show help ─────────────────────────────────────────────────────────

if ($Help) {
    Show-Help
    return
}

# ── Validate parameters ──────────────────────────────────────────────

if (-not $Interactive -and -not $Runbook) {
    Write-Err "Either -Runbook or -Interactive must be specified."
    Write-Host ""
    Show-Help
    exit 1
}

# ── Install Docker CE ────────────────────────────────────────────────

function Install-DockerCE {
    Write-Info "Installing Docker CE (Community Edition) for Windows..."

    if (-not (Test-Administrator)) {
        Write-Err "Administrator privileges required to install Docker CE."
        Write-Host "  Please re-run this script as Administrator."
        exit 1
    }

    # 1. Enable Containers feature
    Write-Info "Checking Windows Containers feature..."
    $containersFeature = Get-WindowsOptionalFeature -Online -FeatureName Containers
    if ($containersFeature.State -ne "Enabled") {
        Write-Info "Enabling Containers feature (may require restart)..."
        Enable-WindowsOptionalFeature -Online -FeatureName Containers -All -NoRestart
        $script:needsRestart = $true
    } else {
        Write-Info "Containers feature is already enabled."
    }

    # 2. Enable Hyper-V (needed for isolation on client SKUs)
    Write-Info "Checking Hyper-V feature..."
    $hypervFeature = Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V -ErrorAction SilentlyContinue
    if ($hypervFeature -and $hypervFeature.State -ne "Enabled") {
        Write-Info "Enabling Hyper-V feature (may require restart)..."
        Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V -All -NoRestart
        $script:needsRestart = $true
    } elseif ($hypervFeature) {
        Write-Info "Hyper-V feature is already enabled."
    }

    if ($script:needsRestart) {
        Write-Warn "A restart is required to complete feature installation."
        Write-Warn "Please restart your machine and re-run this script."
        exit 0
    }

    # 3. Download and install Docker CE binaries
    Write-Info "Downloading Docker CE..."
    $downloadDir = "$env:TEMP\DockerCEDownloads"
    New-Item -ItemType Directory -Path $downloadDir -Force | Out-Null

    # Get latest stable Docker CE version for Windows
    $dockerZipUrl = "https://download.docker.com/win/static/stable/x86_64/"
    try {
        $page = Invoke-WebRequest -Uri $dockerZipUrl -UseBasicParsing
        $latestZip = ($page.Links | Where-Object { $_.href -match "docker-\d+.*\.zip$" } |
            Sort-Object -Property href -Descending | Select-Object -First 1).href
        $dockerDownloadUrl = "${dockerZipUrl}${latestZip}"
    } catch {
        # Fallback to a known version
        $dockerDownloadUrl = "https://download.docker.com/win/static/stable/x86_64/docker-27.4.1.zip"
        $latestZip = "docker-27.4.1.zip"
    }

    $zipPath = Join-Path $downloadDir $latestZip
    Write-Info "Downloading $dockerDownloadUrl ..."
    Invoke-WebRequest -Uri $dockerDownloadUrl -OutFile $zipPath -UseBasicParsing

    # 4. Extract binaries
    Write-Info "Extracting Docker binaries..."
    Expand-Archive -Path $zipPath -DestinationPath $downloadDir -Force
    $dockerBinDir = Join-Path $downloadDir "docker"

    # 5. Install binaries to Program Files
    $installDir = "$env:ProgramFiles\Docker"
    if (-not (Test-Path $installDir)) {
        New-Item -ItemType Directory -Path $installDir -Force | Out-Null
    }
    Copy-Item -Path "$dockerBinDir\*" -Destination $installDir -Force -Recurse
    Write-Info "Docker binaries installed to $installDir"

    # 6. Add to system PATH
    $machinePath = [Environment]::GetEnvironmentVariable("PATH", "Machine")
    if ($machinePath -notlike "*$installDir*") {
        [Environment]::SetEnvironmentVariable("PATH", "$machinePath;$installDir", "Machine")
        $env:PATH = "$env:PATH;$installDir"
        Write-Info "Added $installDir to system PATH."
    }

    # 7. Register and start Docker service
    Write-Info "Registering Docker service..."
    & "$installDir\dockerd.exe" --register-service 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "Docker service may already be registered, continuing..."
    }

    Write-Info "Starting Docker service..."
    Start-Service docker -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 5

    # 8. Verify
    $svc = Get-Service docker -ErrorAction SilentlyContinue
    if ($svc -and $svc.Status -eq "Running") {
        Write-Info "Docker CE is running!"
        & "$installDir\docker.exe" version
    } else {
        Write-Err "Docker service failed to start. Check Event Viewer for details."
        exit 1
    }

    # 9. Clean up residual Docker Desktop context if present
    $dockerConfigDir = "$env:USERPROFILE\.docker"
    if (Test-Path $dockerConfigDir) {
        $configFile = Join-Path $dockerConfigDir "config.json"
        if (Test-Path $configFile) {
            $config = Get-Content $configFile -Raw | ConvertFrom-Json
            if ($config.currentContext -eq "desktop-linux" -or $config.currentContext -eq "desktop-windows") {
                Write-Warn "Removing residual Docker Desktop context..."
                $config.currentContext = "default"
                $config | ConvertTo-Json -Depth 10 | Set-Content $configFile -Encoding UTF8
            }
        }
    }

    # Also clear DOCKER_HOST if it points to Docker Desktop
    $currentHost = [Environment]::GetEnvironmentVariable("DOCKER_HOST", "User")
    if ($currentHost -and $currentHost -like "*dockerDesktop*") {
        Write-Warn "Removing DOCKER_HOST pointing to Docker Desktop..."
        [Environment]::SetEnvironmentVariable("DOCKER_HOST", $null, "User")
        Remove-Item Env:\DOCKER_HOST -ErrorAction SilentlyContinue
    }

    # Clean up downloads
    Remove-Item -Recurse -Force $downloadDir -ErrorAction SilentlyContinue
    Write-Info "Docker CE installation complete!"
}

# ── Install Docker if requested ──────────────────────────────────────

if ($InstallDocker) {
    $dockerExe = Get-Command docker -ErrorAction SilentlyContinue
    if ($dockerExe) {
        Write-Info "Docker is already installed: $(docker --version)"
        # Make sure service is running
        $svc = Get-Service docker -ErrorAction SilentlyContinue
        if ($svc -and $svc.Status -ne "Running") {
            Write-Info "Starting Docker service..."
            Start-Service docker
            Start-Sleep -Seconds 3
        }
    } else {
        Install-DockerCE
    }
}

# ── Verify Docker is available ───────────────────────────────────────

$dockerExe = Get-Command docker -ErrorAction SilentlyContinue
if (-not $dockerExe) {
    Write-Err "Docker is not installed."
    Write-Host "  Run with -InstallDocker to install automatically:"
    Write-Host "  .\quick-container.ps1 -InstallDocker -Interactive"
    exit 1
}

# Verify Docker daemon is reachable (auto-fix common issues)
$dockerConnected = $false
$null = docker info 2>&1
if ($LASTEXITCODE -eq 0) {
    $dockerConnected = $true
}

if (-not $dockerConnected) {
    Write-Warn "Cannot connect to Docker daemon, attempting auto-fix..."

    # Fix 1: Remove residual Docker Desktop context config
    $dockerConfigFile = "$env:USERPROFILE\.docker\config.json"
    if (Test-Path $dockerConfigFile) {
        try {
            $config = Get-Content $dockerConfigFile -Raw | ConvertFrom-Json
            if ($config.currentContext -and $config.currentContext -ne "default") {
                Write-Info "Resetting Docker context from '$($config.currentContext)' to 'default'..."
                $config.currentContext = "default"
                $config | ConvertTo-Json -Depth 10 | Set-Content $dockerConfigFile -Encoding UTF8
            }
        } catch {
            Write-Warn "Removing corrupted Docker config..."
            Remove-Item -Recurse -Force "$env:USERPROFILE\.docker" -ErrorAction SilentlyContinue
        }
    }

    # Fix 2: Clear DOCKER_HOST if it points to Docker Desktop
    $envHost = $env:DOCKER_HOST
    if ($envHost -and $envHost -like "*dockerDesktop*") {
        Write-Info "Clearing DOCKER_HOST pointing to Docker Desktop..."
        Remove-Item Env:\DOCKER_HOST -ErrorAction SilentlyContinue
        [Environment]::SetEnvironmentVariable("DOCKER_HOST", $null, "User")
    }

    # Fix 3: Set DOCKER_HOST to Docker CE pipe explicitly
    if (-not $env:DOCKER_HOST) {
        $env:DOCKER_HOST = "npipe:////./pipe/docker_engine"
        Write-Info "Set DOCKER_HOST to npipe:////./pipe/docker_engine"
    }

    # Fix 4: Start Docker service if not running
    $svc = Get-Service docker -ErrorAction SilentlyContinue
    if ($svc -and $svc.Status -ne "Running") {
        Write-Info "Starting Docker service..."
        Start-Service docker -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 5
    }

    # Fix 5: Grant current user access to Docker pipe via docker-users group
    $dockerOutput = docker version 2>&1 | Out-String
    if ($dockerOutput -match "permission denied|Access is denied") {
        Write-Warn "Permission denied accessing Docker pipe."
        if (Test-Administrator) {
            $username = [Environment]::UserName
            Write-Info "Adding '$username' to docker-users group..."
            & net localgroup docker-users /add 2>$null
            & net localgroup docker-users $username /add 2>$null
            Write-Info "Added '$username' to docker-users group."
        } else {
            Write-Info "Attempting to elevate to fix permissions..."
            $username = [Environment]::UserName
            try {
                Start-Process powershell -ArgumentList "-NoProfile -Command `"net localgroup docker-users /add 2>`$null; net localgroup docker-users $username /add 2>`$null`"" -Verb RunAs -Wait -ErrorAction Stop
                Write-Info "Added '$username' to docker-users group."
                Write-Warn "You may need to log out and log back in for group changes to take effect."
            } catch {
                Write-Warn "Could not elevate to fix permissions automatically."
            }
        }
    }

    # Retry
    $null = docker info 2>&1
    if ($LASTEXITCODE -eq 0) {
        $dockerConnected = $true
        Write-Info "Docker connection fixed successfully!"
    }
}

if (-not $dockerConnected) {
    # Provide specific error message based on the failure type
    $dockerOutput = docker version 2>&1 | Out-String
    if ($dockerOutput -match "permission denied|Access is denied") {
        Write-Err "Permission denied accessing Docker daemon."
        Write-Host ""
        Write-Info "Fix: Run this script as Administrator, or add your user to the docker-users group:"
        Write-Host "  # Run as Administrator:"
        Write-Host "  net localgroup docker-users $([Environment]::UserName) /add"
        Write-Host "  # Then log out and log back in"
    } else {
        Write-Err "Cannot connect to Docker daemon after auto-fix attempts."
        Write-Host ""
        Write-Info "Manual fixes to try:"
        Write-Host "  1. Start the Docker service:  Start-Service docker"
        Write-Host "  2. Fix Docker context:        docker context use default"
        Write-Host "  3. Set correct pipe:          `$env:DOCKER_HOST = 'npipe:////./pipe/docker_engine'"
        Write-Host "  4. Remove Desktop config:     Remove-Item -Recurse ~\.docker"
        Write-Host "  5. Run as Administrator:      Right-click PowerShell -> Run as Administrator"
    }
    exit 1
}

# Show Docker version
Write-Info "Docker is ready: $(docker --version)"

# ── Pull image ───────────────────────────────────────────────────────

if ($Pull) {
    Write-Info "Pulling image: $Image"
    docker pull $Image
    if ($LASTEXITCODE -ne 0) {
        Write-Err "Failed to pull image: $Image"
        exit 1
    }
} else {
    Write-Info "Using image: $Image"
    # Check if image exists locally, pull if not
    $null = docker image inspect $Image 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "Image not found locally, pulling..."
        docker pull $Image
        if ($LASTEXITCODE -ne 0) {
            Write-Err "Failed to pull image: $Image"
            exit 1
        }
    }
}

# ── Build LISA variables ─────────────────────────────────────────────

$allVariables = @()
if ($Variable) { $allVariables += $Variable }
if ($SubscriptionId) { $allVariables += "subscription_id:$SubscriptionId" }
if ($Token) {
    $allVariables += "auth_type:token"
    $allVariables += "azure_arm_access_token:$Token"
}

# ── Determine runbook type ───────────────────────────────────────────
# -InternalRunbook: force treat as container internal path (no mount)
# Absolute paths (C:\...) or explicit relative (.\, ./) are external
# Bare relative paths (lisa/microsoft/...) default to container internal

$runbookIsExternal = $false
$runbookContainerPath = $Runbook
if ($Runbook) {
    if ($InternalRunbook) {
        Write-Info "Using container internal runbook (forced): $Runbook"
    } elseif ([System.IO.Path]::IsPathRooted($Runbook) -or $Runbook -match '^\.\\'  -or $Runbook -match '^\.\/' ) {
        if (Test-Path $Runbook) {
            $runbookIsExternal = $true
            Write-Info "Using external runbook file: $Runbook"
        } else {
            Write-Err "External runbook file not found: $Runbook"
            exit 1
        }
    } else {
        # Bare relative path like "lisa/microsoft/runbook/azure.yml" -> container internal
        Write-Info "Using container internal runbook: $Runbook"
    }
}

# ── Build docker run command ─────────────────────────────────────────

# Remove any existing container with the same name (ignore all errors)
$prevEAP = $ErrorActionPreference
$ErrorActionPreference = "SilentlyContinue"
docker rm -f $ContainerName *>$null
$ErrorActionPreference = $prevEAP
Start-Sleep -Seconds 2

$dockerArgs = @("run")

if (-not $Keep) {
    $dockerArgs += "--rm"
}

$dockerArgs += "--name"
$dockerArgs += $ContainerName

if ($Interactive) {
    $dockerArgs += "-it"
} else {
    $dockerArgs += "-i"
}

# Use process isolation
$dockerArgs += "--isolation=$Isolation"
Write-Info "Using $Isolation isolation"

# Network mode: 'transparent' bypasses NAT and uses host's physical network (fixes DNS)
# 'nat' uses Docker's default NAT networking
if ($Network -eq "transparent") {
    # Create transparent network if it doesn't exist
    $prevEAP2 = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    $existingNet = docker network inspect lisa-transparent 2>$null
    $ErrorActionPreference = $prevEAP2
    if ($LASTEXITCODE -ne 0) {
        Write-Info "Creating transparent Docker network 'lisa-transparent'..."
        docker network create -d transparent lisa-transparent
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "Failed to create transparent network, falling back to NAT"
            $Network = "nat"
        }
    }
    if ($Network -eq "transparent") {
        $dockerArgs += "--network=lisa-transparent"
        Write-Info "Using transparent network (host physical network, no NAT)"
    }
}

if ($Network -eq "nat") {
    # Pass host DNS servers for NAT mode
    $dnsServers = Get-DnsClientServerAddress -AddressFamily IPv4 |
        Where-Object { $_.ServerAddresses } |
        Select-Object -ExpandProperty ServerAddresses -Unique |
        Where-Object { $_ -ne "127.0.0.1" -and $_ -ne "::1" } |
        Select-Object -First 2
    if ($dnsServers) {
        foreach ($dns in $dnsServers) {
            $dockerArgs += "--dns"
            $dockerArgs += $dns
        }
        Write-Info "Using NAT network with host DNS: $($dnsServers -join ', ')"
    }
}

# Mount external runbook
if ($runbookIsExternal) {
    $runbookFullPath = (Resolve-Path $Runbook).Path
    $runbookDir = Split-Path $runbookFullPath -Parent
    $runbookFile = Split-Path $runbookFullPath -Leaf
    $dockerArgs += "-v"
    $dockerArgs += "${runbookDir}:C:\runbook"
    $runbookContainerPath = "C:\runbook\$runbookFile"
}

# Mount local directory
if ($MountPath) {
    if (-not (Test-Path $MountPath)) {
        Write-Err "Mount path does not exist: $MountPath"
        exit 1
    }
    $mountFullPath = (Resolve-Path $MountPath).Path
    $dockerArgs += "-v"
    $dockerArgs += "${mountFullPath}:C:\workspace"
}

# Mount log path
if (-not $Interactive -and $LogPath) {
    if (-not (Test-Path $LogPath)) {
        New-Item -ItemType Directory -Path $LogPath -Force | Out-Null
    }
    $logFullPath = (Resolve-Path $LogPath).Path
    $dockerArgs += "-v"
    $dockerArgs += "${logFullPath}:C:\app\lisa\runtime"
    Write-Info "Logs will be saved to: $logFullPath"
}

# Add extra args
if ($ExtraArgs) {
    $dockerArgs += ($ExtraArgs -split '\s+')
}

# Image
$dockerArgs += $Image

# Command
if ($Interactive) {
    $dockerArgs += "powershell"
} else {
    $dockerArgs += "lisa"
    $dockerArgs += "-r"
    $dockerArgs += $runbookContainerPath

    foreach ($v in $allVariables) {
        $dockerArgs += "-v"
        $dockerArgs += $v
    }
}

# ── Display command (mask secrets) ───────────────────────────────────

$displayArgs = $dockerArgs | ForEach-Object {
    if ($_ -match "(token|secret|password|key|credential).*:" -or $_ -match "^eyJ") {
        "***MASKED***"
    } else { $_ }
}
Write-Info "Executing: docker $($displayArgs -join ' ')"
Write-Host ""

# ── Run container ────────────────────────────────────────────────────

& docker @dockerArgs
$exitCode = $LASTEXITCODE

if ($exitCode -eq 0) {
    Write-Info "LISA container completed successfully."
    if (-not $Interactive -and $LogPath -and (Test-Path $LogPath)) {
        Write-Info "Logs saved to: $((Resolve-Path $LogPath).Path)"
    }
} else {
    Write-Err "LISA container exited with code: $exitCode"
    if (-not $Interactive -and $LogPath -and (Test-Path $LogPath)) {
        Write-Info "Check logs at: $((Resolve-Path $LogPath).Path)"
    }
    exit $exitCode
}
