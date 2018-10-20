# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    Verify Production Checkpoint feature.
.Description
    This script will format and mount connected disk in the VM.
    After that it will proceed with making a Production Checkpoint on test VM.
#>

param([String] $TestParams)

function Main {
    param (
        $TestParams
    )

    $currentTestResult = CreateTestResultObject
    $resultArr = @()

    try{
        $testResult = $null

        $captureVMData = $allVMData
        $VMName = $captureVMData.RoleName
        $HvServer= $captureVMData.HyperVhost
        $Ipv4 = $captureVMData.PublicIP
        $VMPort= $captureVMData.SSHPort

        # Change the working directory to where we need to be
        Set-Location $WorkingDirectory

        LogMsg "Check host version and skip TC in case of older than WS2016"
        $BuildNumber =  Get-HostBuildNumber $HvServer
        if ($BuildNumber -eq 0) {
            throw "Invalid Windows build number"
        }
        elseif ($BuildNumber -lt 10500) {
            LogMsg "Info: Feature supported only on WS2016 and newer"
        }

        # Check if AddVhdxHardDisk doesn't add a VHD disk to Gen2 VM
        if ($TestParams.IDE) {
            $vmGen = Get-VMGeneration  -vmName  $VMName -hvServer $HvServer
            if ($vmGen -eq 2) {
                throw "Cannot add VHD file to Gen2 VM. Skipping."
            }
        }

        # Check to see Linux VM is running VSS backup daemon
        $remoteScript="STOR_VSS_Check_VSS_Daemon.sh"
        $stateFile = "stor_vss_daemon_state.txt"
        $Hypervcheck = "echo '${password}' | sudo -S -s eval `"export HOME=``pwd``;bash ${remoteScript} > Hypervcheck.log`""
        RunLinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort $Hypervcheck -runAsSudo
        RemoteCopy -download -downloadFrom $Ipv4 -files "/home/${user}/state.txt" `
            -downloadTo $LogDir -port $VMPort -username $user -password $password
        rename-item -path ${LogDir}\state.txt -newname $stateFile
        RemoteCopy -download -downloadFrom $Ipv4 -files "/home/${user}/Hypervcheck.log" `
            -downloadTo $LogDir -port $VMPort -username $user -password $password
        $contents = Get-Content -Path $LogDir\$stateFile
        if (($contents -eq "TestAborted") -or ($contents -eq "TestFailed")) {
            throw "Running $remoteScript script failed on VM!"
        }

        LogMsg "Info: VSS Daemon is running"

        # Stop the VSS daemon gracefully
        $remoteScript="PartitionDisks.sh"
        $stateFile = "partition_disk_state.txt"
        $MountPartition = "echo '${password}' | sudo -S -s eval `"export HOME=``pwd``;bash ${remoteScript} > PartitionCheck.log`""
        RunLinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort $MountPartition -runAsSudo
        RemoteCopy -download -downloadFrom $Ipv4 -files "/home/${user}/state.txt" `
            -downloadTo $LogDir -port $VMPort -username $user -password $password
        rename-item -path ${LogDir}\state.txt -newname $stateFile
        RemoteCopy -download -downloadFrom $Ipv4 -files "/home/${user}/PartitionCheck.log" `
            -downloadTo $LogDir -port $VMPort -username $user -password $password
        $contents = Get-Content -Path $LogDir\$stateFile
        if (($contents -eq "TestAborted") -or ($contents -eq "TestFailed")) {
            throw "Running $remoteScript script failed on VM!"
        }

        # Create a file on the VM
        LogMsg "Creating TestFile1"
        $testfile1="Testfile_$(Get-Random -minimum 1 -maximum 1000)"
        $mnt_1="/mnt/1"
        $mnt_2="/mnt/2"
        RunLinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort -command "touch $mnt_1/${testfile1}" -runAsSudo
        if (-not $?)
        {
             throw "Cannot create file ${testfile1} in /mnt/1"
        }
        RunLinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort -command "touch $mnt_2/${testfile1}" -runAsSudo
        if (-not $?)
        {
             throw "Cannot create file ${testfile1} in /mnt/2"
        }

        $vm = Get-VM -Name $VMName -ComputerName $HvServer
        # Check if we can set the Production Checkpoint as default
        if ($vm.CheckpointType -ne "ProductionOnly"){
            Set-VM -Name $VMName -ComputerName $HvServer -CheckpointType ProductionOnly
        }
        $random = Get-Random -minimum 1024 -maximum 4096
        $snapshot = "TestSnapshot_$random"

        LogMsg "Info : creating Production Checkpoint ${snapshot} of VM ${VMName}"
        Checkpoint-VM -Name $VMName -SnapshotName $snapshot -ComputerName $HvServer
        if (-not $?)
        {
            throw "Could not create Production checkpoint with $snapshot"
        }

        # Create another file on the VM
        LogMsg "Creating TestFile2"
        $testfile2="Testfile_$(Get-Random -minimum 1 -maximum 1000)"
        RunLinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort -command "touch $mnt_1/${testfile2}" -runAsSudo
        if (-not $?)
        {
             throw "Cannot create file ${testfile2} in /mnt/1"
        }
        RunLinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort -command "touch $mnt_2/${testfile2}" -runAsSudo
        if (-not $?)
        {
             throw "Cannot create file ${testfile2} in /mnt/2"
        }
        LogMsg "Info : Restoring Production Checkpoint ${snapshot}"
        Restore-VMSnapshot -VMName $VMName -Name $snapshot -ComputerName $HvServer -Confirm:$false

        #
        # Starting the VM
        #
        Start-VM $VMName -ComputerName $HvServer

        #
        # Waiting for the VM to run again and respond to SSH - port 22
        #
        $timeout = 500
        while ($timeout -gt 0) {
            if ( (Test-TCP $Ipv4 $VMPort) -eq "True" ) {
                break
            }

            Start-Sleep -seconds 2
            $timeout -= 2
        }
        if ($timeout -eq 0) {
            throw "Error: Test case timed out waiting for VM to boot"
        }

        # Mount the partitions
        RunLinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort -command "mount /dev/sdc1 /mnt/1; mount /dev/sdc2 /mnt/2" -runAsSudo
        if ($TestParams.DUALMOUNT) {
            RunLinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort -command "mount /dev/sdd1 /mnt/1;  mount /dev/sdd2 /mnt/2" -runAsSudo
        }
        $sts1 = Check-FileInLinuxGuest -VMPassword $password -VMPort $VMPort -VMUserName $user -Ipv4 $Ipv4 -fileName "/mnt/1/${testfile1}"
        $sts2 = Check-FileInLinuxGuest -VMPassword $password -VMPort $VMPort -VMUserName $user -Ipv4 $Ipv4 -fileName "/mnt/2/${testfile1}"
        if (-not $sts1 -or -not $sts2)
        {
            LogErr "TestFile1 is not present, it should be present on the VM"
            $testResult = $resultFail
        }
        $sts1 = Check-FileInLinuxGuest -VMPassword $password -VMPort $VMPort -VMUserName $user -Ipv4 $Ipv4 -fileName "/mnt/1/${testfile2}"
        $sts2 = Check-FileInLinuxGuest -VMPassword $password -VMPort $VMPort -VMUserName $user -Ipv4 $Ipv4 -fileName "/mnt/2/${testfile2}"
        if ($sts1 -or $sts2) {
            LogErr "TestFile2 is present,it should not be present on the VM"
            $testResult = $resultFail
        }
        #
        # Delete the snapshot
        #
        LogMsg "Info : Deleting Snapshot ${snapshot} of VM ${VMName}"
        # First, unmount the partitions
        if ($TestParams.DUALMOUNT) {
            RunLinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort -command "umount /dev/sdd1;  umount /dev/sdd2" -runAsSudo
        }
        RunLinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort -command "umount /dev/sdc1; umount /dev/sdc2" -runAsSudo

        Remove-VMSnapshot -VMName $VMName -Name $snapshot -ComputerName $HvServer

        if( $testResult -ne $resultFail){
            LogMsg "Info : Only the first file is present. Test succeeded"
            $testResult=$resultPass
        }
    } catch {
        $ErrorMessage =  $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        LogErr "EXCEPTION : $ErrorMessage at line: $ErrorLine"
    } finally {
        if (!$testResult) {
            $testResult = $resultAborted
        }
        $resultArr += $testResult
    }
    $currentTestResult.TestResult = GetFinalResultHeader -resultarr $resultArr
	return $currentTestResult.TestResult
}

Main -TestParams (ConvertFrom-StringData $TestParams.Replace(";","`n"))
