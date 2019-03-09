# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    Run the Hot Add NIC test case.

.Description
    This test script will hot add a synthetic NIC to a running Gen 2 VM.
#>
param([String] $TestParams,
      [object] $AllVmData)

function Main {
    param (
        $VMName,
        $HvServer,
        $Ipv4,
        $VMPort,
        $VMUserName,
        $VMPassword,
        $RootDir,
        $TestParams
    )
    $switch_name= "External"
    $nicName = "Hot Add NIC"
    $remoteScript = "NET-Verify-HotAdd-MultiNIC.sh"

    # Read parameters
    $params = $TestParams.TrimEnd(";").Split(";")
    foreach ($p in $params) {
        $fields = $p.Split("=")
        switch ($fields[0].Trim()) {
            "nic_action" { $nic_action = $fields[1].Trim() }
            default {}  # unknown param - just ignore it
        }
    }

    # Change the working directory to where we should be
    Write-LogInfo "Changing directory to '${rootDir}'"
    Set-Location $RootDir

    # Verify the target VM is a Gen2 VM
    $vm = Get-VM -Name $VMName -ComputerName $HvServer -ErrorAction SilentlyContinue
    if ($vm.Generation -ne 2) {
        Write-LogWarn "This test requires a Gen2 VM."
        return "SKIPPED"
    }

    # Verify Windows Server version
    $osInfo = Get-HostBuildNumber $HvServer
    if (-not $osInfo) {
        Write-LogErr "Unable to collect Operating System information"
        return "FAIL"
    }
    if ($osInfo -le 9600) {
        Write-LogErr "This test requires Windows Server 2016 or higher"
        return "FAIL"
    }

    # Verify the target VM does not have a Hot Add NIC.  If it does, then assume
    # there is a test configuration or setup issue, and fail the test.
    #
    # Note: When adding a synthetic NIC, the default name will be "Network Adapter".
    #       When this script adds a NIC, the name "Hot Add NIC" will be assigned
    #       to the hot added NIC rather than the default name.  This allows us to
    #       check that there are no synthetic NICs with the name "Hot Add NIC".
    #       It also makes it easy to remove the hot added NIC since we can find
    #       the hot added NIC by name.
    Write-LogInfo "Ensure the VM does not have a Synthetic NIC with the name '${nicName}'"
    $null = Get-VMNetworkAdapter -VMName $VMName -Name "${nicName}" -ComputerName $HvServer -ErrorAction SilentlyContinue
    if ($?) {
        Write-LogErr "VM '${VMName}' already has a NIC named '${nicName}'"
        return "FAIL"
    }


    # Hot Add a Synthetic NIC to the VM.  Specify a NIC name of "Hot Add NIC".
    # This will make it easy to later identify the NIC to remove.
    Write-LogInfo "Hot add a synthetic NIC with a name of '${nicName}' using switch '${switch_name}'"
    Add-VMNetworkAdapter -VMName $VMName -SwitchName "${switch_name}" -Name "${nicName}" -ComputerName $HvServer
    if (-not $?) {
        Write-LogErr "Unable to Hot Add NIC to VM '${VMName}' on server '${HvServer}'"
        return "FAIL"
    }
    Start-Sleep -s 3

    # Run the NET-Verify-HotAdd-MultiNIC.sh on the VM to verify the VM detected the hot add/remove
    if ($nic_action -eq "remove") {
        Remove-VMNetworkAdapter -VMName $VMName -Name "${nicName}" -ComputerName $HvServer -ErrorAction SilentlyContinue
        if (-not $?) {
            Write-LogErr "Unable to remove hot added NIC"
            return "FAIL"
        }
    }
    $stateFile = "${LogDir}\state.txt"
    $NETVerifyHotAddMultiNIC = "echo '${VMPassword}' | sudo -S -s eval `"export HOME=``pwd``;bash ${remoteScript} ${nic_action} > NET-Verify-${nic_action}-MultiNIC.log`""
    Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort $NETVerifyHotAddMultiNIC -runAsSudo
    Copy-RemoteFiles -download -downloadFrom $Ipv4 -files "/home/${VMUserName}/state.txt" `
        -downloadTo $LogDir -port $VMPort -username $VMUserName -password $VMPassword
    Copy-RemoteFiles -download -downloadFrom $Ipv4 -files "/home/${VMUserName}/NET-Verify-${nic_action}-MultiNIC.log" `
        -downloadTo $LogDir -port $VMPort -username $VMUserName -password $VMPassword
    $contents = Get-Content -Path $stateFile
    if (($contents -eq "TestAborted") -or ($contents -eq "TestFailed")) {
        Write-LogErr "Failed to verify the VM detected the hot ${nic_action} !"
        return "FAIL"
    }
    else {
        Write-LogInfo "Test PASSED,VM detected the hot ${nic_action} !"
        return "PASS"
    }

}
Main -VMName $AllVMData.RoleName -HvServer $GlobalConfig.Global.Hyperv.Hosts.ChildNodes[0].ServerName `
    -Ipv4 $AllVMData.PublicIP -VMPort $AllVMData.SSHPort `
    -VMUserName $user -vmPassword $password -RootDir $WorkingDirectory `
    -TestParams $TestParams
