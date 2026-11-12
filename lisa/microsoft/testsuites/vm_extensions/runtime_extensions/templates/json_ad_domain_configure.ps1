# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

param(
    [string]$DomainName,
    [string]$AdminUsername,
    [string]$AdminPassword,
    [switch]$Resume
)

$ErrorActionPreference = 'Stop'
$root = 'C:\lisa\ad'
if (!$Resume) {
    . "$root\package\CreateADPDC.ps1"
    $credential = [PSCredential]::new($AdminUsername, (ConvertTo-SecureString $AdminPassword -AsPlainText -Force))
    $configurationData = @{
        AllNodes = @(@{
            NodeName = 'localhost'
            PSDscAllowPlainTextPassword = $true
            PSDscAllowDomainUser = $true
        })
    }
    CreateADPDC -DomainName $DomainName -Admincreds $credential -ConfigurationData $configurationData -OutputPath "$root\configuration" | Out-Null

    # Azure orchestrates reboots so that they cannot interrupt CSE or Run Command.
    [DSCLocalConfigurationManager()]
    configuration ControlledReboots {
        Node localhost {
            Settings {
                RebootNodeIfNeeded = $false
                ActionAfterReboot = 'StopConfiguration'
                ConfigurationMode = 'ApplyOnly'
                RefreshMode = 'Push'
            }
        }
    }
    ControlledReboots -OutputPath "$root\lcm" | Out-Null
    Set-DscLocalConfigurationManager -Path "$root\lcm" -ErrorAction Stop
    Start-DscConfiguration -Path "$root\configuration" -Wait -Force -ErrorAction Stop 4>$null | Out-Null
} else {
    Start-DscConfiguration -UseExisting -Wait -Force -ErrorAction Stop 4>$null | Out-Null
}
$status = Get-DscConfigurationStatus -ErrorAction Stop
if ($status.Status -eq 'Failure') {
    throw "DSC configuration failed: $($status.Error)"
}
if ($status.RebootRequested) {
    Write-Output 'LISA_DSC_REBOOT_REQUIRED'
} elseif ($status.Status -eq 'Success') {
    Write-Output 'LISA_DSC_READY'
} else {
    throw "Unexpected DSC configuration status: $($status.Status)"
}
