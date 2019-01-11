# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
    Verify the VM is providing heartbeat.

.Description
    Use the PowerShell cmdlet to verify the heartbeat
	provided by the test VM is detected by the Hyper-V
	server.
#>

param([String] $TestParams,
      [object] $AllVmData)

function Main {
    param (
        $Ipv4,
        $VMPort,
        $RootDir,
        $VMName,
        $HvServer,
        $TestParams
    )

    # Parse the testParams string
    $params = $TestParams.Split(';')
    foreach ($p in $params) {
        if ($p.Trim().Length -eq 0) {
            continue
        }
        $tokens = $p.Trim().Split('=')
        if ($tokens.Length -ne 2) {
            Write-LogInfo "Warn: test parameter '$p' is being ignored because it appears to be malformed"
            continue
        }
    }

    if (-not $Ipv4) {
        Write-LogErr " The IPv4 test parameter was not provided."
        return "FAIL"
    }
    if (-not $RootDir) {
        Write-LogErr " The RootDir test parameter is not defined."
        return "FAIL"
    } else {
        Set-Location $RootDir
    }

    # Test if the VM is running
    $vm = Get-VM $VMName -ComputerName $HvServer
    $hvState = $vm.State

    if ($hvState -ne "Running") {
        "Error: VM $VMName is not in running state. Test failed."
        return "FAIL"
    }

    # We need to wait for TCP port 22 to be available on the VM
    $heartbeatTimeout = 300
    while ($heartbeatTimeout -gt 0) {
        if ( (Test-TCP $Ipv4 $VMPort) -eq "True" ) {
            break
        }
        Start-Sleep -seconds 5
        $heartbeatTimeout -= 5
    }

    if ($heartbeatTimeout -eq 0) {
        Write-LogErr " Test case timed out for VM to enter in the Running state"
        return "FAIL"
    }

    # Check the VMs heartbeat
    $hb = Get-VMIntegrationService -VMName $VMName -ComputerName $HvServer -Name "Heartbeat"
    if ($($hb.Enabled) -eq "True" -And $($vm.Heartbeat) -eq "OkApplicationsUnknown") {
        Write-LogInfo "Heartbeat detected"
    } else {
        Write-LogErr "Test Failed: VM heartbeat not detected!"
        Write-LogErr "Heartbeat not detected while the Heartbeat service is enabled"
        return "FAIL"
    }

    #Disable the VMs heartbeat
    Disable-VMIntegrationService -ComputerName $HvServer -VMName $VMName -Name "Heartbeat"
    $status = Get-VMIntegrationService -VMName $VMName -ComputerName $HvServer -Name "Heartbeat"
    if ($status.Enabled -eq $False -And $vm.Heartbeat -eq "Disabled") {
        Write-LogErr "Heartbeat disabled successfully"
    } else {
        Write-LogErr "Unable to disable the Heartbeat service"
        return "FAIL"
    }

    #Check the VMs heartbeat again
    Enable-VMIntegrationService -ComputerName $HvServer -VMName $VMName -Name "Heartbeat"
    $hb = Get-VMIntegrationService -VMName $VMName -ComputerName $HvServer -Name "Heartbeat"
    if ($($hb.Enabled) -eq "True" -And $($vm.Heartbeat) -eq "OkApplicationsUnknown") {
        Write-LogInfo "Heartbeat detected again"
        return "PASS"
    } else {
        Write-LogErr "Test Failed: VM heartbeat not detected again!"
        Write-LogErr " Heartbeat not detected after re-enabling the Heartbeat service"
        return "FAIL"
    }
}

Main -VMName $AllVMData.RoleName -HvServer $GlobalConfig.Global.Hyperv.Hosts.ChildNodes[0].ServerName `
         -Ipv4 $AllVMData.PublicIP -VMPort $AllVMData.SSHPort `
         -RootDir $WorkingDirectory -TestParams $TestParams
