# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
    This script tests the debug kernel basic functionality.

.Description
    The script will install the debug kernel and boot into debug kernel,
    then check whether have call trace
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
    $cmd = ". utils.sh && install_package 'kernel-debug' && grub2-set-default 0"
    $null = Run-LinuxCmd -username $global:user -password $global:password -ip $AllVMData.PublicIP `
        -port $AllVMData.SSHPort -command $cmd -runAsSudo -runMaxAllowedTime 480

    # Rebooting the VM
    $TestProvider.RestartAllDeployments($AllVMData)

    Write-LogInfo "VM boots up successfully after reboot..."
    # Get IP again to avoid IP address change after reboot

    $sts = Run-LinuxCmd -username $global:user -password $global:password -ip $AllVMData.PublicIP `
        -port $AllVMData.SSHPort -command "uname -r | grep debug" -ignoreLinuxExitCode

    if (-not $sts) {
        Write-LogErr "VM fails to boot up with debug kernel!"
        return "FAIL"
    }
    else {
        Write-LogInfo "VM boots up with the debug kernel $sts successfully..."
    }

    # Wait for 1 minute and check call traces
    $trace = "${LogDir}\check_traces.log"
    $null = Run-LinuxCmd -username $global:user -password $global:password -ip $AllVMData.PublicIP -port $AllVMData.SSHPort ". utils.sh && UtilsInit && CheckCallTracesWithDelay 60" -runAsSudo
    Copy-RemoteFiles -download -downloadFrom $AllVMData.PublicIP -files "/home/$($global:user)/check_traces.log" `
        -downloadTo $LogDir -port $AllVMData.SSHPort -username $global:user -password $global:password
    $contents = Get-Content -Path $trace
    if ($contents -contains "ERROR") {
        Write-LogErr "Test FAIL , Call Traces found!"
        return "FAIL"
    }
    else {
        Write-LogInfo "Test PASSED , No call traces found!"
        return "PASS"
    }
}
Main
