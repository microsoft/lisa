# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

param([String] $TestParams,
      [object] $AllVmData)

function Main {
    param (
        $VMName,
        $HvServer,
        $VMPort,
        $VMUserName,
        $VMPassword,
        $IPv4,
        $TestParams
    )
    $bootproto = "static"
    $currentDir = "$((Get-Location).Path)\"

    # Get MAC for test VM NIC
    $macFileTestVM = "macAddress.file"
    $macFileTestVM = "$currentDir"+"$macFileTestVM"
    $streamReaderTestVM = [System.IO.StreamReader] $macFileTestVM
    $vm1MacAddress = $streamReaderTestVM.ReadLine()
    Write-LogInfo "vm1 MAC: $vm1MacAddress"
    $streamReaderTestVM.close()

    # Get MAC for dependency VM
    $macFileDependencyVM = "macAddressDependency.file"
    $macFileDependencyVM ="$currentDir"+"$macFileDependencyVM"
    $streamReaderDependencyVM = [System.IO.StreamReader] $macFileDependencyVM
    $vm2MacAddress = $streamReaderDependencyVM.ReadLine()
    Write-LogInfo "vm2 MAC: $vm2MacAddress"
    $streamReaderDependencyVM.close()

    $params = $TestParams.Split(';')
    foreach ($p in $params) {
        $fields = $p.Split("=")
        switch ($fields[0].Trim()) {
            "VM2NAME" { $vm2Name = $fields[1].Trim() }
            "STATIC_IP" { $vm1StaticIP = $fields[1].Trim() }
            "STATIC_IP2" { $vm2StaticIP = $fields[1].Trim() }
            "NETMASK" { $netmask = $fields[1].Trim() }
            default {}
        }
    }

    # Get IP from dependency VM
    $vm2ipv4 = Get-IPv4ViaKVP $VM2Name $HvServer

    # Make sure the VM supports vxlan before testing it
    [int]$majorVersion = Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $vm2ipv4 `
        -port $VMPort -command ". utils.sh && GetOSVersion && echo `$os_RELEASE"
    [int]$minorVersion = Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $vm2ipv4 `
        -port $VMPort -command ". utils.sh && GetOSVersion && echo `$os_UPDATE"
    if ((($majorVersion -le 6) -and ($minorVersion -le 4)) -or $majorVersion -le 5) {
        Write-LogWarn "RHEL ${majorVersion}.${minorVersion} doesn't support vxlan"
        return "ABORT"
    }

    $kernel = Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $vm2ipv4 `
        -port $VMPort -command "uname -a | grep 'i686\|i386'" -ignoreLinuxExitCode:$true
    if ($kernel.Contains("i686") -or $kernel.Contains("i386")){
        Write-LogWarn "Vxlan not supported on 32 bit OS"
        return "ABORT"
    }

    # Configure interface on test VM
    if (-not $vm1MacAddress.Contains(":")) {
        for ($i=2; $i -lt 16; $i=$i+2) {
            $vm1MacAddress = $vm1MacAddress.Insert($i,':')
            $i++
        }
    }
    $null = Set-GuestInterface $VMUserName $IPv4 $VMPort $VMPassword $vm1MacAddress `
        $vm1StaticIP $bootproto $netmask $VMName
    if (-not $?) {
        Write-LogErr "Couldn't configure the test interface on $VMName"
        return "FAIL"
    }

    # Upload NET-Configure-Vxlan.sh on both VMs
    Copy-RemoteFiles -upload -uploadTo $IPv4 -Port $VMPort `
        -files ".\Testscripts\Linux\utils.sh,.\Testscripts\Linux\NET-Configure-Vxlan.sh" `
        -Username $VMUserName -password $VMPassword
    if (-not $?) {
        Write-LogErr "Failed to send utils.sh to VM!"
        return "FAIL"
    }

    Copy-RemoteFiles -upload -uploadTo $vm2ipv4 -Port $VMPort `
        -files ".\Testscripts\Linux\NET-Configure-Vxlan.sh" `
        -Username $VMUserName -password $VMPassword
    if (-not $?) {
        Write-LogErr "Failed to send utils.sh to VM!"
        return "FAIL"
    }

    # Run NET-Configure-Vxlan.sh on both VMs
    $cmdToSendVM1 = "chmod u+x NET-Configure-Vxlan.sh && ./NET-Configure-Vxlan.sh $vm1StaticIP local"
    Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $IPv4 -port $VMPort -command $cmdToSendVM1 `
        -ignoreLinuxExitCode:$true -RunAsSudo
    if (-not $?) {
        Write-LogErr "Failed to configure vxlan on vm $VMName"
        return "FAIL"
    } else {
        Write-LogInfo "Succesfully configured vxlan on $VMName"
    }

    $cmdToSendVM2 = "chmod u+x NET-Configure-Vxlan.sh && ./NET-Configure-Vxlan.sh $vm2StaticIP remote"
    Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $vm2ipv4 -port $VMPort -command $cmdToSendVM2 `
        -ignoreLinuxExitCode:$true -RunAsSudo
    if (-not $?) {
        Write-LogErr "Failed to configure vxlan on vm $VM2Name"
        return "FAIL"
    } else {
        Write-LogInfo "Succesfully configured vxlan on $VM2Name"
    }

    # Send rsync command on the first VM
    Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $IPv4 -port $VMPort -command "cp /home/${VMUsername}/net_constants.sh ." -ignoreLinuxExitCode:$true -RunAsSudo
    Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $IPv4 -port $VMPort -command ". utils.sh; test_rsync" -ignoreLinuxExitCode:$true -RunAsSudo
    $state = Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $IPv4 -port $VMPort -command "cat state.txt" -ignoreLinuxExitCode:$true -RunAsSudo
    Write-LogInfo "State file on VM1 has the following content $state"
    if ($state -notMatch "Completed") {
        Write-LogErr "Failed to ping from $VMName to VM2 using vxlan"
        return "FAIL"
    }

    # Wait 3 minutes for files to be transferred & test connection to make
    # sure VM1 is still up
    Write-LogInfo "Sleeping for 180 seconds"
    Start-Sleep -Seconds 180

    $timeout=200
    do {
        Start-Sleep -Seconds 5
        $timeout -= 5
        if ($timeout -eq 0) {
            Write-LogErr "Connection lost to the first VM"
            return "FAIL"
        }
    } until(Test-NetConnection $IPv4 -Port 22 -WarningAction SilentlyContinue | Where-Object { $_.TcpTestSucceeded } )

    # Check if files were received on vm2
    Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $vm2ipv4 -port $VMPort -command ". utils.sh; test_rsync_files" -ignoreLinuxExitCode:$true
    $state = Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $vm2ipv4 -port $VMPort -command "cat state.txt" -ignoreLinuxExitCode:$true
    Write-LogInfo "State file on VM1 has the following content $state"
    if ($state -notMatch "Completed") {
        Write-LogErr "Files that were sent from $VMName were not found on VM2"
        return "FAIL"
    }
    return "PASS"
}

Main -VMName $AllVMData.RoleName -HvServer $GlobalConfig.Global.Hyperv.Hosts.ChildNodes[0].ServerName `
     -VMPort $AllVMData.SSHPort -VMUserName $user -VMPassword $password `
     -IPv4 $AllVMData.PublicIP -TestParams $TestParams
