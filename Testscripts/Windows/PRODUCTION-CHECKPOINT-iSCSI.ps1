# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
    Verify Production Checkpoint feature.

.Description
    This script will connect to a iSCSI target, format and mount the iSCSI disk.
    After that it will proceed with making a Production Checkpoint on test VM.

.Parameter vmName
    Name of the VM to perform the test with.

.Parameter hvServer
    Name of the Hyper-V server hosting the VM.

.Parameter testParams
    A semicolon separated list of test parameters.

#>

param([string] $testParams)

#######################################################################
#
# Main script body
#
#######################################################################
function Main {
    param (
        $TestParams
    )
    try{
        $testResult = $null
        $captureVMData = $allVMData
        $vmName = $captureVMData.RoleName
        $hvServer= $captureVMData.HyperVhost
        $ipv4 = $captureVMData.PublicIP
        $port= $captureVMData.SSHPort

        LogMsg "Covers Production Checkpoint Testing"
        # Change the working directory to where we need to be
        Set-Location $WorkingDirectory
        # if host build number lower than 10500, skip test
        $BuildNumber = Get-HostBuildNumber $hvServer
        if ($BuildNumber -eq 0) {
            throw "Invalid Build Number"
        }
        elseif ($BuildNumber -lt 10500) {
            throw "Feature supported only on WS2016 and newer"
        }
        # Check if the Vm VHD in not on the same drive as the backup destination
        $vm = Get-VM -Name $vmName -ComputerName $hvServer
        # Check to see Linux VM is running VSS backup daemon
        $remoteScript="STOR_VSS_Check_VSS_Daemon.sh"
        $stateFile = "stor_vss_daemon_state.txt"
        $Hypervcheck = "echo '${password}' | sudo -S -s eval `"export HOME=``pwd``;bash ${remoteScript} > Hypervcheck.log`""
        RunLinuxCmd -username $user -password $password -ip $ipv4 -port $port $Hypervcheck -runAsSudo
        RemoteCopy -download -downloadFrom $ipv4 -files "/home/${user}/state.txt" `
            -downloadTo $LogDir -port $port -username $user -password $password
        rename-item -path ${LogDir}\state.txt -newname $stateFile
        RemoteCopy -download -downloadFrom $ipv4 -files "/home/${user}/Hypervcheck.log" `
            -downloadTo $LogDir -port $port -username $user -password $password
        $contents = Get-Content -Path $LogDir\$stateFile
        if (($contents -eq "TestAborted") -or ($contents -eq "TestFailed")) {
            throw "Running $remoteScript script failed on VM!"
        }

        LogMsg "VSS Daemon is running"
        # Run the remote iSCSI partition script
        $remoteScript = "STOR_VSS_ISCSI_PartitionDisks.sh"
        $remoteLog = "STOR_VSS_ISCSI_PartitionDisks.log"
        $stateFile = "stor_vss_iscsi_state.txt"
        $Hypervcheck = "echo '${password}' | sudo -S -s eval `"export HOME=``pwd``;bash ${remoteScript} > $remoteLog`""
        RunLinuxCmd -username $user -password $password -ip $ipv4 -port $port $Hypervcheck -runAsSudo
        RemoteCopy -download -downloadFrom $ipv4 -files "/home/${user}/state.txt" `
            -downloadTo $LogDir -port $port -username $user -password $password
        rename-item -path ${LogDir}\state.txt -newname $stateFile
        RemoteCopy -download -downloadFrom $ipv4 -files "/home/${user}/$remoteLog" `
            -downloadTo $LogDir -port $port -username $user -password $password
        $contents = Get-Content -Path $LogDir\$stateFile
        if (($contents -eq "TestAborted") -or ($contents -eq "TestFailed")) {
            throw "Running $remoteScript script failed on VM!"
        }

        LogMsg "$remoteScript execution on VM: Success"
        # Create a file on the VM
        RunLinuxCmd -username $user -password $password -ip $ipv4 -port $port -command "touch /mnt/1/TestFile1" -runAsSudo
        if (-not $?) {
            throw "Can not create file /mnt/1/TestFile1"
        }

        RunLinuxCmd -username $user -password $password -ip $ipv4 -port $port -command "touch /mnt/2/TestFile1" -runAsSudo
        if (-not $?) {
            throw "Can not create file /mnt/2/TestFile1"
        }

        Start-Sleep -seconds 30

        #Check if we can set the Production Checkpoint as default
        if ($vm.CheckpointType -ne "ProductionOnly") {
            Set-VM -Name $vmName -CheckpointType ProductionOnly -ComputerName $hvServer
            if (-not $?) {
               throw "Could not set Production as Checkpoint type"
            }
        }

        $random = Get-Random -minimum 1024 -maximum 4096
        $snapshot = "TestSnapshot_$random"
        Checkpoint-VM -Name $vmName -SnapshotName $snapshot -ComputerName $hvServer
        if (-not $?) {
            throw "Could not create checkpoint"
        }

        # Create another file on the VM
        $sts1 = RunLinuxCmd -username $user -password $password -ip $ipv4 -port $port -command "touch /mnt/1/TestFile2" -runAsSudo
        if (-not $?) {
            throw "Can not create file /mnt/1/TestFile2"
        }
        $sts2 = RunLinuxCmd -username $user -password $password -ip $ipv4 -port $port -command "touch /mnt/2/TestFile2" -runAsSudo
        if (-not $?) {
            throw "Can not create file /mnt/2/TestFile2"
        }

        LogMsg "Restore the VM snapshot"
        Restore-VMSnapshot -VMName $vmName -Name $snapshot -ComputerName $hvServer -Confirm:$false
        if (-not $?)
        {
            throw "Could not restore checkpoint"
        }

        LogMsg "Start the VM after restoring the snapshot"
        #
        # Starting the VM
        #
        Start-VM $vmName -ComputerName $hvServer

        LogMsg "Wait for VM to run again"
        #
        # Waiting for the VM to run again and respond to SSH - port 22
        #
        $timeout = 500
        while ($timeout -gt 0) {
            if ( (Test-TCP $ipv4 $port) -eq "True" ) {
                break
            }
            Start-Sleep -seconds 2
            $timeout -= 2
        }
        if ($timeout -eq 0) {
            throw "Test case timed out waiting for VM to boot"
        }

        LogMsg "Mount the partitions"
        # Mount the partitions
        RunLinuxCmd -username $user -password $password -ip $ipv4 -port $port -command "mount /dev/sdc1 /mnt/1; mount /dev/sdc2 /mnt/2" -runAsSudo

        LogMsg "Check TestFile1 and TestFile2 in VM"
        # Check the files
        $sts1 = Check-FileInLinuxGuest -VMPassword $password -VMPort $port -VMUserName $user -Ipv4 $ipv4 -fileName "/mnt/1/TestFile1"
        $sts2 = Check-FileInLinuxGuest -VMPassword $password -VMPort $port -VMUserName $user -Ipv4 $ipv4 -fileName "/mnt/2/TestFile1"
        if (-not $sts1 -or -not $sts2) {
            LogErr "TestFile1 is not present, it should be present on the VM"
            $testResult = $resultFail
        }
        $sts1 = Check-FileInLinuxGuest -VMPassword $password -VMPort $port -VMUserName $user -Ipv4 $ipv4 -fileName "/mnt/1/TestFile2"
        $sts2 = Check-FileInLinuxGuest -VMPassword $password -VMPort $port -VMUserName $user -Ipv4 $ipv4 -fileName "/mnt/2/TestFile2"
        if ($sts1 -or $sts2)
        {
            LogErr "TestFile2 is present,it should not be present on the VM"
            $testResult = $resultFail
        }
        LogMsg "Only the first file is present. Test succeeded"

        #
        # Delete the snapshot
        #
        LogMsg "Deleting Snapshot ${Snapshot} of VM ${vmName}"

        # First, unmount the partitions
        RunLinuxCmd -username $user -password $password -ip $ipv4 -port $port -command "umount /dev/sdc1; umount /dev/sdc2" -runAsSudo

        Remove-VMSnapshot -VMName $vmName -Name $snapshot -ComputerName $hvServer
        if( $testResult -ne $resultFail) {
            LogMsg "Only the first file is present. Test succeeded"
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

Main -TestParams  (ConvertFrom-StringData $TestParams.Replace(";","`n"))
