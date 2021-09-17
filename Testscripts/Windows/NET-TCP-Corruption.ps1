# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    Run NET_Corruption in the guest VM in order to install netcat
    and set the desired corruption. Start netcat listen process on
    the VM and the receive process on windows host. Check for call traces.
    Compare file hashes.
#>

param([String] $TestParams,
      [object] $AllVmData)

function Main {
    param (
        $VMName,
        $HvServer,
        $IPv4,
        $VMPort,
        $VMPassword,
        $VMUserName
    )
    $port = 1234
    $sourceFilePath = "/tmp/testfile"
    $destionationFilePath = ".\testfile"
    $netcatScriptPath = "listen.sh"
    $netcatBinPath = ".\Tools\nc.exe"

    # nc.exe should be in Tools
    if (-not (Test-Path $netcatBinPath)) {
        Write-LogWarn "Unable to find netcat binary"
        return "SKIPPED"
    }

    # Copy dependency files to VM
    Copy-RemoteFiles -upload -uploadTo $IPv4 -Port $VMPort `
        -files ".\Testscripts\Linux\utils.sh,.\Testscripts\Linux\NET-Corruption.sh" `
        -Username $VMUserName -password $VMPassword

    # Run NET-Corruption.sh on the VM
    Write-LogInfo "Configuring VM"
    $cmdToSend = "cp /home/${VMUserName}/constants.sh . ; bash NET-Corruption.sh ${sourceFilePath} ${port} ${netcatScriptPath} 2>/dev/null"
    $retVal = Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $IPv4 -port $VMPort `
        -command $cmdToSend -ignoreLinuxExitCode:$true -RunAsSudo
    $state = Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $IPv4 -port $VMPort `
        -command "cat state.txt" -ignoreLinuxExitCode:$true -RunAsSudo
    if ($state -notMatch "Completed") {
        Write-LogErr "NET-TCP-Corruption.sh failed on guest"
        return "FAIL"
    }

    Write-LogInfo "Checking system logs path"
    $sts = Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $IPv4 -port $VMPort `
        -command "[[ -f /var/log/syslog ]];echo `$?" -ignoreLinuxExitCode:$true -RunAsSudo
    if ($sts -eq "1") {
        $logPath = '/var/log/messages'
    } else {
        $logPath = '/var/log/syslog'
    }

    # Start netcat on guest
    Write-LogInfo "Starting netcat server on VM Job"
    $cmd = "setsid ./$netcatScriptPath >/dev/null 2>&1"
    Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $IPv4 -port $VMPort `
        -command $cmd -ignoreLinuxExitCode:$true -RunInBackGround -RunAsSudo

    $ipAddr = (Get-VMNetworkAdapter -VMName ${VMName} -ComputerName $HvServer)[1].IPAddresses[0]
    $cmd = "cmd.exe /C " + "'" + "${netcatBinPath} -v -w 2 ${ipAddr} ${port} > ${destionationFilePath}" + "'"
    Write-LogInfo "Running command ${cmd} on host"
    $cmd | Out-File ./nccmd.ps1
    $sts = ./nccmd.ps1

    Write-LogInfo "Checking for call traces in ${logPath}"
    $grepCmd = "grep -i 'Call Trace' ${logPath}"
    $retVal = Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $IPv4 -port $VMPort `
            -command $grepCmd -ignoreLinuxExitCode:$true -RunAsSudo
    if ($retVal) {
        Write-LogErr "Call traces found in ${logPath}"
        return "FAIL"
    }

    Write-LogInfo "Comparing hashes"
    $localHash = (Get-FileHash -Algorithm MD5 $destionationFilePath).Hash
    $remoteHash = Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $IPv4 -port $VMPort `
        -command "md5sum ${sourceFilePath}" -ignoreLinuxExitCode:$true -RunAsSudo
    $remoteHash = $remoteHash.Split(" ")[0]
    if (-not $remoteHash) {
        Write-LogErr "Unable to get file hash from VM"
        return "FAIL"
    }

    Write-LogInfo "File hashes: ${remoteHash} - ${localHash}"
    if ($remoteHash.ToUpper() -ne $localHash) {
        Write-LogErr "File hashes do not match."
        return "FAIL"
    }

    Write-LogInfo "Test completed successfully"
    return "PASS"
}

Main -VMName $AllVMData.RoleName -HvServer $GlobalConfig.Global.Hyperv.Hosts.ChildNodes[0].ServerName `
    -IPv4 $AllVMData.PublicIP -VMPort $AllVMData.SSHPort -VMPassword $password `
    -VMUserName $user
