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
            Write-LogInfo "Feature supported only on WS2016 and newer"
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
        $testfile1="Testfile1_$(Get-Random -minimum 1 -maximum 1000)"
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
            Set-VM -Name $VMName -ComputerName $HvServer -CheckpointType ProductionOnly | Out-Null
        }
        $random = Get-Random -minimum 1024 -maximum 4096
        $snapshot = "TestSnapshot_$random"

        Write-LogInfo "Creating Production Checkpoint ${snapshot} of VM ${VMName}"
        Checkpoint-VM -Name $VMName -SnapshotName $snapshot -ComputerName $HvServer | Out-Null
        if (-not $?)
        {
            throw "Could not create Production checkpoint with $snapshot"
        }

        # Create another file on the VM
        Write-LogInfo "Creating TestFile2"
        $testfile2="Testfile2_$(Get-Random -minimum 1 -maximum 1000)"
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
        Write-LogInfo "Restoring Production Checkpoint ${snapshot}"
        Restore-VMSnapshot -VMName $VMName -Name $snapshot -ComputerName $HvServer -Confirm:$false | Out-Null

        #
        # Starting the VM
        #
        Start-VM $VMName -ComputerName $HvServer | Out-Null

        #
        # Waiting for the VM to run again and respond to SSH - port 22
        #
        $timeout = 500
        $retval = Wait-ForVMToStartSSH -Ipv4addr $Ipv4 -StepTimeout $timeout
        if ($retval -eq $False) {
            throw "Error: Test case timed out waiting for VM to boot"
        }

        # Mount the partitions
        $allDisks = Run-LinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort `
            -command "ls /dev/sd* | grep -o '/dev/sd*[^0-9]' | uniq" -runAsSudo
        $linuxOSDiskName = Run-LinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort `
            -command ". utils.sh && get_OSdisk" -runAsSudo
        # After restarting the VM, the OS disk name may swap to another one like /dev/sdc, so skip it
        $availableDisks = @()
        foreach ( $disk in ($allDisks -split "/dev/") ) {
            if ($disk -and ($disk.Trim() -ne $linuxOSDiskName)) {
                $availableDisks += $disk.Trim()
            }
        }

        # The disk swap, dual mount and resource disk make mount/umount complex
        # It has to traverse all disks combination if DUALMOUNT is true
        $disk_combination = @()
        if ($TestParams.DUALMOUNT) {
            $rest = New-Object Collections.ArrayList
            $availableDisks[1..($availableDisks.Length - 1)] | foreach { $rest.Add($_) | Out-Null }
            $prefix = $availableDisks[0]
            $(while ($rest) {
                foreach ($suffix in $rest) {
                    $disk_combination += $prefix
                    $disk_combination += $suffix
                }
                $prefix = $rest[0]
                $rest.RemoveAt(0)
            })
            $disk_combination += $disk_combination[-1..($disk_combination.Length-2)]
        } else {
            $disk_combination = $availableDisks
        }

        $testResultTmp = $resultFail
        for ($i = 0; $i -le $disk_combination.Length; $i++) {
            $mount_1st_disk = $disk_combination[$i]
            Run-LinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort `
                -command "mount /dev/${mount_1st_disk}1 /mnt/1; mount /dev/${mount_1st_disk}2 /mnt/2" -runAsSudo
            if ($TestParams.DUALMOUNT) {
                $i++
                $mount_2nd_disk = $disk_combination[$i]
                Run-LinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort `
                    -command "mount /dev/${mount_2nd_disk}1 /mnt/1; mount /dev/${mount_2nd_disk}2 /mnt/2" -runAsSudo
            }
            $sts1 = Check-FileInLinuxGuest -VMPassword $password -VMPort $VMPort -VMUserName $user -Ipv4 $Ipv4 -fileName "/mnt/1/${testfile1}"
            $sts2 = Check-FileInLinuxGuest -VMPassword $password -VMPort $VMPort -VMUserName $user -Ipv4 $Ipv4 -fileName "/mnt/2/${testfile1}"
            if (-not $sts1 -or -not $sts2)
            {
                Write-LogWarn "TestFile1 is not present, try other disk"
                if ($TestParams.DUALMOUNT) {
                    Run-LinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort `
                        -command "umount /dev/${mount_2nd_disk}1; umount /dev/${mount_2nd_disk}2" -runAsSudo
                }
                Run-LinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort `
                    -command "umount /dev/${mount_1st_disk}1; umount /dev/${mount_1st_disk}2" -runAsSudo
                continue
            } else {
                $testResultTmp = $resultPass
                break
            }
        }

        if( $testResultTmp -eq $resultPass){
            $sts1 = Check-FileInLinuxGuest -VMPassword $password -VMPort $VMPort -VMUserName $user -Ipv4 $Ipv4 -fileName "/mnt/1/${testfile2}"
            $sts2 = Check-FileInLinuxGuest -VMPassword $password -VMPort $VMPort -VMUserName $user -Ipv4 $Ipv4 -fileName "/mnt/2/${testfile2}"
            if ($sts1 -or $sts2) {
                Write-LogErr "TestFile2 is present,it should not be present on the VM"
                $testResult = $resultFail
            }
        } else {
            Write-LogErr "TestFile1 is not present, it should be present on the VM"
            $testResult = $resultFail
        }

        #
        # Delete the snapshot
        #
        Write-LogInfo "Deleting Snapshot ${snapshot} of VM ${VMName}"
        # First, unmount the partitions
        if ($TestParams.DUALMOUNT) {
            Run-LinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort `
                -command "umount /dev/${mount_2nd_disk}1; umount /dev/${mount_2nd_disk}2" -runAsSudo
        }
        Run-LinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort `
            -command "umount /dev/${mount_1st_disk}1; umount /dev/${mount_1st_disk}2" -runAsSudo

        Remove-VMSnapshot -VMName $VMName -Name $snapshot -ComputerName $HvServer | Out-Null

        if( $testResult -ne $resultFail){
            Write-LogInfo "Only the first file is present. Test succeeded"
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
