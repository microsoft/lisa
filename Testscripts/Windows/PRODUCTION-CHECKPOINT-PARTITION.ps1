# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    Verify Production Checkpoint feature.
.Description
    This script will format and mount connected disk in the VM.
    After that it will proceed with making a Production Checkpoint on test VM.
#>

param([string] $testParams, [object] $AllVmData)

function Main {
    param (
        $TestParams, $allVMData
    )

    $currentTestResult = Create-TestResultObject
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

        Write-LogInfo "Check host version and skip TC in case of older than WS2016"
        $BuildNumber =  Get-HostBuildNumber $HvServer
        if ($BuildNumber -eq 0) {
            throw "Invalid Windows build number"
        }
        elseif ($BuildNumber -lt 10500) {
            Write-LogInfo "Info: Feature supported only on WS2016 and newer"
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
        $retval = Invoke-RemoteScriptAndCheckStateFile $remoteScript $user $password $Ipv4 $VMPort
        if ($retval -eq $False) {
            throw "Running $remoteScript script failed on VM!"
        }
        Write-LogInfo "VSS Daemon is running"

        # Run the Partition Disk script
        $remoteScript="PartitionDisks.sh"
        $retval = Invoke-RemoteScriptAndCheckStateFile $remoteScript $user $password $Ipv4 $VMPort
        if ($retval -eq $False) {
            throw "Running $remoteScript script failed on VM!"
        }
        # Create a file on the VM
        Write-LogInfo "Creating TestFile1"
        $testfile1="Testfile_$(Get-Random -minimum 1 -maximum 1000)"
        $mnt_1="/mnt/1"
        $mnt_2="/mnt/2"
        Run-LinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort -command "touch $mnt_1/${testfile1}" -runAsSudo
        if (-not $?)
        {
             throw "Cannot create file ${testfile1} in /mnt/1"
        }
        Run-LinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort -command "touch $mnt_2/${testfile1}" -runAsSudo
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

        Write-LogInfo "Info : creating Production Checkpoint ${snapshot} of VM ${VMName}"
        Checkpoint-VM -Name $VMName -SnapshotName $snapshot -ComputerName $HvServer
        if (-not $?)
        {
            throw "Could not create Production checkpoint with $snapshot"
        }

        # Create another file on the VM
        Write-LogInfo "Creating TestFile2"
        $testfile2="Testfile_$(Get-Random -minimum 1 -maximum 1000)"
        Run-LinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort -command "touch $mnt_1/${testfile2}" -runAsSudo
        if (-not $?)
        {
             throw "Cannot create file ${testfile2} in /mnt/1"
        }
        Run-LinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort -command "touch $mnt_2/${testfile2}" -runAsSudo
        if (-not $?)
        {
             throw "Cannot create file ${testfile2} in /mnt/2"
        }
        Write-LogInfo "Info : Restoring Production Checkpoint ${snapshot}"
        Restore-VMSnapshot -VMName $VMName -Name $snapshot -ComputerName $HvServer -Confirm:$false

        #
        # Starting the VM
        #
        Start-VM $VMName -ComputerName $HvServer

        #
        # Waiting for the VM to run again and respond to SSH - port 22
        #
        $timeout = 500
        $retval = Wait-ForVMToStartSSH -Ipv4addr $Ipv4 -StepTimeout $timeout
        if ($retval -eq $False) {
            throw "Error: Test case timed out waiting for VM to boot"
        }

        # Mount the partitions
        Run-LinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort -command "mount /dev/sdc1 /mnt/1; mount /dev/sdc2 /mnt/2" -runAsSudo
        if ($TestParams.DUALMOUNT) {
            Run-LinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort -command "mount /dev/sdd1 /mnt/1;  mount /dev/sdd2 /mnt/2" -runAsSudo
        }
        $sts1 = Check-FileInLinuxGuest -VMPassword $password -VMPort $VMPort -VMUserName $user -Ipv4 $Ipv4 -fileName "/mnt/1/${testfile1}"
        $sts2 = Check-FileInLinuxGuest -VMPassword $password -VMPort $VMPort -VMUserName $user -Ipv4 $Ipv4 -fileName "/mnt/2/${testfile1}"
        if (-not $sts1 -or -not $sts2)
        {
            Write-LogErr "TestFile1 is not present, it should be present on the VM"
            $testResult = $resultFail
        }
        $sts1 = Check-FileInLinuxGuest -VMPassword $password -VMPort $VMPort -VMUserName $user -Ipv4 $Ipv4 -fileName "/mnt/1/${testfile2}"
        $sts2 = Check-FileInLinuxGuest -VMPassword $password -VMPort $VMPort -VMUserName $user -Ipv4 $Ipv4 -fileName "/mnt/2/${testfile2}"
        if ($sts1 -or $sts2) {
            Write-LogErr "TestFile2 is present,it should not be present on the VM"
            $testResult = $resultFail
        }
        #
        # Delete the snapshot
        #
        Write-LogInfo "Info : Deleting Snapshot ${snapshot} of VM ${VMName}"
        # First, unmount the partitions
        if ($TestParams.DUALMOUNT) {
            Run-LinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort -command "umount /dev/sdd1;  umount /dev/sdd2" -runAsSudo
        }
        Run-LinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort -command "umount /dev/sdc1; umount /dev/sdc2" -runAsSudo

        Remove-VMSnapshot -VMName $VMName -Name $snapshot -ComputerName $HvServer

        if( $testResult -ne $resultFail){
            Write-LogInfo "Info : Only the first file is present. Test succeeded"
            $testResult=$resultPass
        }
    } catch {
        $ErrorMessage =  $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogErr "EXCEPTION : $ErrorMessage at line: $ErrorLine"
    } finally {
        if (!$testResult) {
            $testResult = $resultAborted
        }
        $resultArr += $testResult
    }
    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
	return $currentTestResult.TestResult
}

Main -TestParams (ConvertFrom-StringData $TestParams.Replace(";","`n")) -allVMData $AllVmData
