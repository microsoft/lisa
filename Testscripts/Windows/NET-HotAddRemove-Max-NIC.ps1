# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    Run the Hot Add Remove Max NIC test case.

.Description
    This test script will hot add 7 synthetic NICs to a running Gen 2 VM.
#>

param([String] $TestParams)

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

    $switchName = "External"
    $remoteScript = "NET-MAX-NICs.sh"
    $remoteScript2 = "NET-Verify-HotAdd-MultiNIC.sh"
    ########################################################################
    $params = $TestParams.Split(";")
    foreach($p in $params)
    {
        $tokens = $p.Trim().Split("=")
        if ($tokens.Length -ne 2)
        {
            continue
        }
        $val = $tokens[1].Trim()
        switch($tokens[0].Trim().ToLower())
        {
		"SYNTHETIC_NICS"{ $nicsAmount  = $val -as [int] }
        default         { continue }
        }
    }

    # Change the working directory to where we should be
    Set-Location $rootDir

    # Verify the target VM is a Gen2 VM
    $vm = Get-VM -Name $VMName -ComputerName $HvServer -ErrorAction SilentlyContinue
    if ($vm.Generation -ne 2) {
        LogWarn "This test requires a Gen2 VM."
        return "ABORTED"
    }

    # Verify Windows Server version
    $osInfo = Get-HostBuildNumber $hvServer
    if (-not $osInfo) {
        LogErr "Unable to collect Operating System information"
        return "ABORTED"
    }
    if ($osInfo -le 9600) {
        LogErr  "This test requires Windows Server 2016 or higher"
        return "ABORTED"
    }

    #	Hot Add maximum number of synthetic NICs
    LogMsg "Hot Adding the maximum number of synthetic NICs ..."
    $addnic = Add-RemoveMaxNIC $vmName $hvServer $switchName "add" $nicsAmount

    # Run the NET_MAX_NIC.sh on the SUT VM to verify the VM detected the hot add
    LogMsg "Verifing the OS detected the NIC was hot add..."

    $stateFile = "${LogDir}\state.txt"
    $NETMaxNICs = "echo '${VMPassword}' | sudo -S -s eval `"export HOME=``pwd``;bash ${remoteScript}  > NETMaxNICs.log`""
    $runcmd = RunLinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort $NETMaxNICs -runAsSudo
    RemoteCopy -download -downloadFrom $Ipv4 -files "/home/${VMUserName}/state.txt" `
        -downloadTo $LogDir -port $VMPort -username $VMUserName -password $VMPassword
    RemoteCopy -download -downloadFrom $Ipv4 -files "/home/${VMUserName}/NETMaxNICs.log" `
        -downloadTo $LogDir -port $VMPort -username $VMUserName -password $VMPassword
    $contents = Get-Content -Path $stateFile
    if (($contents -eq "TestAborted") -or ($contents -eq "TestFailed")) {
        LogErr "Error: Running $remoteScript script failed on VM!"
        return "FAIL"
    }
    else {
        LogMsg "VM detected $nicsAmount NICs have been added!"
    }

    # Check if KVP IP values match the ones present in the VM
    LogMsg "Info : Checking KVP values for each NIC"
    Start-Sleep -s 60
    $kvp_ip = Get-IPv4ViaKVP $vmName $hvServer | Select-Object -uniq
    $vm_ip = RunLinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort -command "ip -4 -o addr show scope global | awk '{print `$4}'" | ForEach-Object {$_.Split('\n')} | ForEach-Object { $_.Split('/')[0]; }

    if ($kvp_ip.length -ne $vm_ip.length) {
        LogErr "IP values sent through KVP are not the same as the ones from the VM"
        LogErr "KVP values : ${kvp_ip} VM values : ${vm_ip}"
        return "FAIL"
    }

    foreach ($ip in $vm_ip) {
        if (-not $kvp_ip -contains $ip) {
            LogErr "IP values sent through KVP are not the same as the ones from the VM"
            LogErr "KVP values : $kvp_ip"
            LogErr "VM values : $vm_ip"
            return "FAIL"
        }
    }

    # Now Hot Remove the NIC
    $removenic = Add-RemoveMaxNIC  $vmName  $hvServer  $switchName "remove" $nicsAmount

    # Run the NET_VerifyHotAddSyntheticNIC.sh on the SUT VM to verify the VM detected the hot remove
    LogMsg "Verifing the OS detected the NIC was hot removed..."
    $action = "remove"
    $stateFile = "${LogDir}\state.txt"
    $logFile = "${LogDir}\NETVerifyHotRemoveMultiNIC.log"
    $HotRemoveMultiNIC = "echo '${VMPassword}' | sudo -S -s eval `"export HOME=``pwd``;bash ${remoteScript2} ${action} > NETVerifyHotRemoveMultiNIC.log`""
    $runcmd2 = RunLinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort $HotRemoveMultiNIC -runAsSudo
    RemoteCopy -download -downloadFrom $Ipv4 -files "/home/${VMUserName}/state.txt" `
        -downloadTo $LogDir -port $VMPort -username $VMUserName -password $VMPassword
    RemoteCopy -download -downloadFrom $Ipv4 -files "/home/${VMUserName}/NETVerifyHotRemoveMultiNIC.log" `
        -downloadTo $LogDir -port $VMPort -username $VMUserName -password $VMPassword
    $contents = Get-Content -Path $stateFile
    $contents2 = Get-Content -Path $logFile
    if (($contents -eq "TestAborted") -or ($contents -eq "TestFailed")) {
        LogErr "Error: Running $remoteScript script failed on VM!"
        return "FAIL"
    }
    if ($contents2 -match "netvsc throwed errors") {
        LogErr "Error: VM '${vmName}' reported that netvsc throwed errors"
        return "FAIL"
    }
    else {
        LogMsg "Test PASSED ,VM detected the hot remove!"
    }
    LogMsg "Multiple NICs Hot Add/Remove successfully..."
    return "PASS"
}

Main -VMName $AllVMData.RoleName -HvServer $xmlConfig.config.Hyperv.Hosts.ChildNodes[0].ServerName `
    -Ipv4 $AllVMData.PublicIP -VMPort $AllVMData.SSHPort -TestParams $TestParams `
    -VMUserName $user -VMPassword $password -RootDir $WorkingDirectory
