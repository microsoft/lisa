# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
    Verify take snapshot and revert snapshot operations work.

.Description
    Tests to see that the virtual machine snapshot operation works as well as
    the revert snapshot operation.
#>

param([string] $TestParams, [object] $AllVMData)

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

    $snapshotname = $null
    $random = Get-Random -minimum 1024 -maximum 4096
    $remoteScript = "STOR-Lis-Disk.sh"
    #######################################################################
    #
    # Main script block
    #
    #######################################################################
    #
    # Checking the mandatory testParams
    #
    $params = $TestParams.Split(";")
    foreach ($p in $params) {
        $fields = $p.Split("=")
        switch ($fields[0].Trim()) {
            "snapshotname" { $snapshotname = $fields[1].Trim() }
            default {}
        }
    }

    if (-not $snapshotname) {
        Write-LogErr "Missing testParam snapshotname value"
        return "FAIL"
    }

    # Change the working directory for the log files
    if (-not (Test-Path $RootDir)) {
        Write-LogErr "The directory `"${RootDir}`" does not exist"
        return "FAIL"
    }
    Set-Location $RootDir

    #
    #Creating a file for snapshot
    #
    $sts = Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort `
           -command "touch /home/$VMUserName/PostSnapData.txt"

    #
    #Run the guest VM side script
    #
    $stateFile = "${LogDir}\state.txt"
    $LISDisk = "echo '${VMPassword}' | sudo -S -s eval `"export HOME=``pwd``;bash ${remoteScript} > LISDisk.log`""
    Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort $LISDisk -runAsSudo | Out-Null
    Copy-RemoteFiles -download -downloadFrom $Ipv4 -files "/home/${VMUserName}/state.txt" `
        -downloadTo $LogDir -port $VMPort -username $VMUserName -password $VMPassword
    Copy-RemoteFiles -download -downloadFrom $Ipv4 -files "/home/${VMUserName}/LISDisk.log" `
        -downloadTo $LogDir -port $VMPort -username $VMUserName -password $VMPassword
    $contents = Get-Content -Path $stateFile
    if (($contents -eq "TestAborted") -or ($contents -eq "TestFailed")) {
        Write-LogErr "Running $remoteScript script failed on VM!"
        return "FAIL"
    }
    Write-LogInfo "Waiting for VM $VMName to shut-down..."
    if ((Get-VM -ComputerName $HvServer -Name $VMName).State -ne "Off") {
        Stop-VM -ComputerName $HvServer -Name $VMName -Force -Confirm:$false
    }

    #
    # Waiting until the VM is off
    #
    if (-not (Wait-ForVmToStop $VMName $HvServer 300)) {
        Write-LogErr "Unable to stop VM!"
        return "FAIL"
    }

    #
    # Take a snapshot then restore the VM to the snapshot
    #
    $Snapshot = "TestSnapshot_$random"
    Write-LogInfo "Taking Snapshot operation on VM, snapshot name - $Snapshot"
    Checkpoint-VM -Name $VMName -SnapshotName $Snapshot -ComputerName $HvServer
    if (-not $?) {
        Write-LogErr "Could not create VM snapshot!"
        return "FAIL"
    }

    Write-LogInfo "Restoring Snapshot operation on VM, snapshot name - $snapshotname"
    Restore-VMSnapshot -VMName $VMName -Name $snapshotname -ComputerName $HvServer -Confirm:$false
    if (-not $?) {
        Write-LogErr "Could not restore VM snapshot!"
        return "FAIL"
    }

    #
    # Start the VM and wait up to 5 minutes for it to come up
    #

    Start-VM $VMName -ComputerName $HvServer

    $newIpv4 = Get-Ipv4AndWaitForSSHStart -VmName $VMName -HvServer $HvServer -Vmport $VMPort -User $VMUserName `
                  -Password $VMPassword -StepTimeout 30
    if (-not $newIpv4) {
        Write-LogErr "Failed to retrieve $VMName IP after snapshot restore"
        return "FAIL"
    }
    #
    # Verify that VM started OK after snapshot restore
    #
    Write-LogInfo "Waiting for VM to boot ..."
    $null = Wait-VMHeartbeatOK -VMName $VMName -HvServer $HvServer `
                -RetryCount 60 -RetryInterval 4
    Write-LogInfo "Checking if the test file is still present..."
    $sts = Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $newIpv4 -port $VMPort `
                -ignoreLinuxExitCode -command  "stat /home/$VMUserName/PostSnapData.txt 2> /dev/null"
    if ($sts) {
        Write-LogErr "File still present in VM"
        return "FAIL"
    }
    Write-LogInfo "VM Snapshot and Restore operations were successful."
    #
    # Delete the snapshot
    #
    Write-LogInfo "Deleting snapshot ${Snapshot} of VM ${vmName}"
    Remove-VMSnapshot -VMName $VMName -Name $Snapshot -ComputerName $HvServer
    if (-not $?) {
        Write-LogErr "Could not delete temporary VM snapshot!"
        return "FAIL"
    }

    return "PASS"
}

Main -VMName $AllVMData.RoleName -HvServer $GlobalConfig.Global.Hyperv.Hosts.ChildNodes[0].ServerName `
    -Ipv4 $AllVMData.PublicIP -VMPort $AllVMData.SSHPort `
    -VMUserName $user -VMPassword $password -RootDir $WorkingDirectory `
    -TestParams $TestParams
