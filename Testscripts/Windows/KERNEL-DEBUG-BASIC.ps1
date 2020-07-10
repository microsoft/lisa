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
    param (
        $VMname,
        $HvServer,
        $Ipv4,
        $VMPort,
        $VMUserName,
        $VMPassword,
        $RootDir,
        $TestParams
)

    if ( ( $global:detectedDistro -imatch "CENTOS") -or ($global:detectedDistro -imatch "REDHAT") ) {
        Write-LogInfo "Test on DISTRO $global:detectedDistro"
    } 
    else {
        Write-LogInfo "Do not support this DISTRO."
        return "SKIPPED"
    }
    $cmd = ". utils.sh && install_package 'kernel-debug' && grub2-set-default 0"
    $null = Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 `
        -port $VMPort -command $cmd -runAsSudo -runMaxAllowedTime 480

    # Rebooting the VM in order to apply the kdump settings
    Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort `
       -command "reboot" -runAsSudo -RunInBackGround | Out-Null
    
    Write-LogInfo "Rebooting VM $VMName after select debug kernel..."
    Start-Sleep 10 # Wait for kvp & ssh services stop

    # Wait for VM boot up and update ip address
    Wait-ForVMToStartSSH -Ipv4addr $Ipv4 -StepTimeout 360 | Out-Null

    Write-LogInfo "VM $VMName boots up successfully after reboot..."
    $sts = Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 `
        -port $VMPort -command "uname -r | grep debug"
    Write-LogInfo "Current kernel version is: $sts"

    if (-not $sts) {
        Write-LogErr "VM $VMName fails to boot up with debug kernel!"
        return "FAIL"
    }
    else {
        Write-LogInfo "VM $VMName boots up debug with kernel successfully..."
    }

    # Wait for 1 minute and check call traces
    $trace = "${LogDir}\check_traces.log"
    Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort ". utils.sh && UtilsInit && CheckCallTracesWithDelay 60" -runAsSudo
    Copy-RemoteFiles -download -downloadFrom $Ipv4 -files "/home/${VMUserName}/check_traces.log" `
        -downloadTo $LogDir -port $VMPort -username $VMUserName -password $VMPassword
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
Main -VMname $AllVMData.RoleName -HvServer $GlobalConfig.Global.HyperV.Hosts.ChildNodes[0].ServerName `
    -Ipv4 $AllVMData.PublicIP -VMPort $AllVMData.SSHPort `
    -VMUserName $user -VMPassword $password -RootDir $WorkingDirectory `
    -TestParams $TestParams
