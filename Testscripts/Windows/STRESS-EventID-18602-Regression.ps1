#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

#Description:
#   This script will start/stop a VM as many times as specified in the
#   count parameter and check that the VM reboots successfully.

param([string] $testParams)

 function Wait-VMState {
    param(
        $VMName,
        $VMState,
        $HvServer,
        $RetryCount=30,
        $RetryInterval=5
    )
     $currentRetryCount = 0
    while ($currentRetryCount -lt $RetryCount -and `
              (Get-VM -ComputerName $hvServer -Name $vmName).State -ne $VMState) {
        LogMsg "Waiting for VM ${VMName} to enter ${VMState} state"
        Start-Sleep -Seconds $RetryInterval
        $currentRetryCount++
    }
    if ($currentRetryCount -eq $RetryCount) {
        LogErr "VM ${VMName} failed to enter ${VMState} state"
        return $false
    }
    return $true
}

function Wait-VMHeartbeatOK {
    param(
        $VMName,
        $HvServer,
        $RetryCount=30,
        $RetryInterval=5
    )
    $currentRetryCount = 0
    do {
        $currentRetryCount++
        Start-Sleep -Seconds $RetryInterval
        LogMsg "Waiting for VM ${VMName} to enter Heartbeat OK state"
    } until ($currentRetryCount -ge $RetryCount -or `
                 (Get-VMIntegrationService -VMName $vmName -ComputerName $hvServer | `
                  Where-Object  { $_.name -eq "Heartbeat" }
              ).PrimaryStatusDescription -eq "OK")
    if ($currentRetryCount -eq $RetryCount) {
        LogMsg "VM ${VMName} failed to enter Heartbeat OK state"
        return $false
    }
    return $true
}

function Wait-VMEvent {
    param(
        $VMName,
        $StartTime,
        $EventCode,
        $HvServer,
        $RetryCount=30,
        $RetryInterval=5
    )
     $currentRetryCount = 0
    while ($currentRetryCount -lt $RetryCount) {
        LogMsg "Checking eventlog for event code $EventCode triggered by VM ${VMName}"
        $currentRetryCount++
        $events = @(Get-WinEvent -FilterHashTable `
            @{LogName = "Microsoft-Windows-Hyper-V-Worker-Admin";
              StartTime = $StartTime; ID = $EventCode} `
            -ComputerName $hvServer -ErrorAction SilentlyContinue)
        foreach ($evt in $events) {
            if ($evt.message.Contains($vmName)) {
                LogMsg "Event code $EventCode triggered by VM ${VMName}"
                LogMsg $evt.message
                return $true
            }
        }
        Start-Sleep $RetryInterval
    }
    if ($currentRetryCount -eq $RetryCount) {
        LogErr "VM ${VMName} failed to trigger event on the host"
        return $false
    }
}

function Main {
    param (
        $HvServer,
        $VMName,
        $Ipv4,
        $VMPort,
        $VMUserName,
        $VMPassword,
        $RootDir
    )

    $params = $testParams.Split(';')
    foreach ($p in $params) {
        if ($p.Trim().Length -eq 0) {
            continue
        }
         $tokens = $p.Trim().Split('=')
         if ($tokens.Length -ne 2) {
            LogMsg "Warn : test parameter '$p' is being ignored because it appears to be malformed"
        }
         if ($tokens[0].Trim() -eq "count") {
            $count = $tokens[1].Trim()
        }
    }

    Set-Location $rootDir

    $vm = Get-VM $VMName -ComputerName $hvServer
    if (-not $vm) {
        LogErr "Cannot find VM ${VMName} on server ${hvServer}"
        LogErr "VM ${VMName} not found"
        return "FAIL"
    }
    if ($($vm.State) -ne "Running") {
        LogErr "VM ${VMName} is not in the running state"
        return "FAIL"
    }
     # Check VM responds to reboot via ctrl-alt-del
    LogMsg "Trying to press ctrl-alt-del from VM's keyboard."
    $VMKB = Get-WmiObject -namespace "root\virtualization\v2" -class "Msvm_Keyboard" `
                -ComputerName $hvServer -Filter "SystemName='$($vm.Id)'"
    $VMKB.TypeCtrlAltDel()
    if($? -eq "True") {
        LogMsg "VM received the ctrl-alt-del signal successfully."
    } else {
        LogErr "VM did not receive the ctrl-alt-del signal successfully."
        return $"FAIL"
    }
    $resultVMState = Wait-VMState -VMName $VMName -HvServer $HvServer -VMState "Running" `
            -RetryCount 60 -RetryInterval 2
    $resultVMHeartbeat = Wait-VMHeartbeatOK -VMName $VMName -HvServer $HvServer `
            -RetryCount 60 -RetryInterval 2
    if (!$resultVMState -or !$resultVMHeartbeat) {
        LogErr "Test case timed out waiting for the VM to reach Running state after receiving ctrl-alt-del."
        return $"FAIL"
    }
     # Check VM can be stress rebooted
    LogMsg "Setting the boot count to 0 for rebooting the VM"
    $bootcount = 0
    $testStartTime = [DateTime]::Now
     while ($count -gt 0) {
        Start-VM -Name $VMName -Confirm:$false
        $resultVMStateOn = Wait-VMState -VMName $VMName -HvServer $HvServer -VMState "Running" `
                -RetryCount 60 -RetryInterval 2
        $resultVMHeartbeat = Wait-VMHeartbeatOK -VMName $VMName -HvServer $HvServer `
                -RetryCount 60 -RetryInterval 2
        Start-Sleep -S 60
        Stop-VM -Name $VMName -Confirm:$false -Force
        $resultVMStateOff = Wait-VMState -VMName $VMName -HvServer $HvServer -VMState "Off" `
                -RetryCount 60 -RetryInterval 2
         if (!$resultVMStateOn -or !$resultVMHeartbeat -or !$resultVMStateOff) {
            LogErr "Test case timed out for VM to go to from Running to Off state"
            return "FAIL"
        }
         if ((Wait-VMEvent -VMName $VMName -HvServer $hvServer -StartTime $testStartTime `
                -EventCode 18602 -RetryCount 2 -RetryInterval 1)) {
            LogErr "VM $VMName triggered a critical event 18602 on the host"
            return "FAIL"
        }
        $count -= 1
        $bootcount += 1
        LogMsg "Boot count:"$bootcount
    }
	Start-VM -Name $VMName -Confirm:$false
    LogMsg "VM rebooted $bootcount times successfully"
    LogMsg "Info: VM did not trigger a critical event 18602 on the host"
    return "PASS"
}

Main -VMName $AllVMData.RoleName -hvServer $xmlConfig.config.Hyperv.Hosts.ChildNodes[0].ServerName `
         -ipv4 $AllVMData.PublicIP -VMPort $AllVMData.SSHPort `
         -VMUserName $user -VMPassword $password -RootDir $WorkingDirectory
