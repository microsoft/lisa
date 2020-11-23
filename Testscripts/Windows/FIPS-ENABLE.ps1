# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
    This script tests the enable fips (Federal Information Processing Standard) mode.

.Description
    The script will enable fips mode and reboot vm to check whether fips mode is enabled
#>
param([String] $TestParams,
      [object] $AllVmData)

function Main {

    if ( ( $global:detectedDistro -imatch "CENTOS") -or ($global:detectedDistro -imatch "REDHAT") ) {
        Write-LogInfo "Test on DISTRO $($global:detectedDistro)"
    }
    else {
        Write-LogWarn "Do not support this DISTRO $($global:detectedDistro)."
        return "SKIPPED"
    }
    $cmd = "command -v fips-mode-setup"
    try {
        $null = Run-LinuxCmd -username $global:user -password $global:password -ip $AllVMData.PublicIP `
        -port $AllVMData.SSHPort -command $cmd -runAsSudo
    }
    catch {
        Write-LogWarn "fips-mode-setup does not exist in the VM, skip test"
        return "SKIPPED"
    }

    Write-LogInfo "fips-mode-setup command exists in the VM"

    $cmd = "fips-mode-setup --enable"
    $null = Run-LinuxCmd -username $global:user -password $global:password -ip $AllVMData.PublicIP `
    -port $AllVMData.SSHPort -command $cmd -runAsSudo

    # Rebooting the VM
    $TestProvider.RestartAllDeployments($AllVMData)

    Write-LogInfo "VM boots up successfully after reboot..."

    $sts = Run-LinuxCmd -username $global:user -password $global:password -ip $AllVMData.PublicIP `
        -port $AllVMData.SSHPort -command "fips-mode-setup --check | grep enabled" -ignoreLinuxExitCode

    if (-not $sts) {
        Write-LogErr "VM fails to boot up with fips mode enabled!"
        return "FAIL"
    }
    else {
        Write-LogInfo "VM boots up with the fips mode enabled successfully..."
        return "PASS"
    }
}
Main
